"""Service layer dla `POST /api/advisor/chat` (Sprint 6.1 PR1 per ADR-007).

Cztery odpowiedzialności:

1. `build_today_state` — zbiera kontekst metryczny z DDB (BIOMETRY queries).
2. `read_history` / `count_today_turns` / `append_message` — DDB chat history
   (`CHAT#{date}#{turn_idx:04d}`, 24h TTL per ADR-007 D6).
3. `build_chat_messages` — kompozycja user message z `<conversation_history>`
   + `<today_context>` + `<user_message>` (forward-compat dla `<retrieved_recipes>`
   w PR2).
4. `call_chat` — wywołuje Anthropic Haiku (free-form text, NO tool_use).

Decyzje implementacyjne:
- Brak ADVISOR_CACHE — chat nie cache'uje (ADR-007 D6, każda tura unikalna).
- Single user message do Anthropic (NIE native multi-turn) — stabilność
  prompt cache (ADR-007 D7).
- PROFILE row read dla `kcal_target`/`protein_target_g` — fallback hardcoded
  defaults (2000/130/70/200) z log warning gdy brak.
- Anthropic SDK retry built-in (default `max_retries=2`); explicit catch dla
  `APIStatusError`/timeout/connection → handler zwraca 503 fail-loud.
- Recent history hard cap = 20 ostatnich tur (ADR-007 D7) — chroni token budget.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from shared.dynamo import get_item, put_item, query_by_pk, sum_metric_today
from shared.logging import get_logger
from shared.ssm import SecretMisconfiguredError, load_secure_secret

from .schemas import ChatMessage, TodayState, TokenUsage

if TYPE_CHECKING:
    from anthropic import Anthropic

logger = get_logger("advisor_chat")

# ─── Constants ─────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY_PARAM = "/bodysync/anthropic/api_key"
# Anthropic API key prefix `sk-ant-api03-` ~108 chars; 50 jako sanity dolny limit.
ANTHROPIC_API_KEY_MIN_LENGTH = 50

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 2048

# Chat history TTL — 24h rolling window (ADR-007 D6).
CHAT_TTL_SECONDS = 86400

# Recent history hard cap przekazywany do LLM (ADR-007 D7) — chroni token budget.
RECENT_HISTORY_LIMIT = 20

# Fallback target dla PROFILE row missing — preferred fallback z log warning
# > 503 z reason=profile_missing. Wartości typowe dla średniego mężczyzny
# 75-80 kg, deficyt 400 kcal:
DEFAULT_KCAL_TARGET = 2000
DEFAULT_PROTEIN_TARGET_G = 130
DEFAULT_FAT_TARGET_G = 70
DEFAULT_CARBS_TARGET_G = 200

# Map BIOMETRY metric_short → value attribute (mirror health_webhook.service
# storage layer). Trzymamy lokalnie żeby advisor nie zależał od api_read.
_CUMULATIVE_VALUE_ATTRS: dict[str, str] = {
    "kcal_in": "kcal",
    "kcal_active": "kcal",
    "kcal_basal": "kcal",
    "protein": "g",
    "steps": "count",
}

# System prompt — file read na cold start (mały plik, deterministic).
_SYSTEM_PROMPT_PATH = Path(__file__).parent / "system_prompt.txt"
_SYSTEM_PROMPT: str = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

# Anthropic client cache (module-level singleton).
_anthropic_client: Anthropic | None = None


# ─── Anthropic client ──────────────────────────────────────────────────────


class AdvisorUnavailableError(RuntimeError):
    """Anthropic API key nie jest skonfigurowane (SSM PLACEHOLDER lub za krótki).

    Handler łapie i zwraca 503 z `reason="api_key_missing"`.
    """


class AdvisorBackendError(RuntimeError):
    """Anthropic API rzuciło 5xx / timeout / connection error po retry,
    lub odpowiedź ma nieoczekiwany shape.

    Handler łapie i zwraca 503 z `reason="advisor_unavailable"`.
    """


def get_anthropic_client() -> Anthropic:
    """Lazy singleton — Anthropic SDK init + SSM key fetch raz per cold start.

    Raises `AdvisorUnavailableError` gdy SSM zwraca PLACEHOLDER (Terraform
    initial state, owner nie wpisał real key) lub key krótszy niż 50 chars.
    """
    global _anthropic_client
    if _anthropic_client is not None:
        return _anthropic_client
    try:
        api_key = load_secure_secret(
            ANTHROPIC_API_KEY_PARAM, min_length=ANTHROPIC_API_KEY_MIN_LENGTH
        )
    except SecretMisconfiguredError as exc:
        raise AdvisorUnavailableError("anthropic_api_key_missing") from exc
    # Lazy import — Anthropic SDK ~3s import cold; nie chcemy płacić w testach
    # które mockują przez `responses` lib (bezpośrednie HTTP intercept).
    from anthropic import Anthropic

    _anthropic_client = Anthropic(api_key=api_key, max_retries=2)
    return _anthropic_client


def _reset_client_for_tests() -> None:
    """Test-only — drop singleton between tests."""
    global _anthropic_client
    _anthropic_client = None


# ─── Context building ──────────────────────────────────────────────────────


def _decimal_to_float(value: Any) -> float:
    """Cast `Decimal | int | float | None` na `float`. None → 0.0 (caller
    używa wyników jako sumy — None bezpiecznie zwija się do 0)."""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


def _query_snapshots_in_range(
    user_id: str, metric_short: str, *, start: date, end: date
) -> list[dict[str, Any]]:
    """Pobierz snapshot rows `BIOMETRY#{date}#{metric_short}` (3-part SK,
    bez timestampu) w przedziale `[start..end]` inclusive.

    Snapshot metrics: weight, body_fat, resting_hr, sleep — single item
    per dzień, last-writer-wins (per health_webhook._make_scalar_upsert).

    Single Query z `begins_with(SK, "BIOMETRY#")` + post-filter w Pythonie
    (cheaper niż N×GetItem dla 7 dni — 1-2 RCU vs 7 round-tripów).
    """
    rows = query_by_pk(f"USER#{user_id}", sk_prefix="BIOMETRY#")
    start_iso = start.isoformat()
    end_iso = end.isoformat()
    items: list[dict[str, Any]] = []
    for row in rows:
        sk = row.get("SK", "")
        # Snapshot SK: "BIOMETRY#YYYY-MM-DD#metric" (dokładnie 3 części).
        parts = sk.split("#")
        if len(parts) != 3 or parts[2] != metric_short:
            continue
        if start_iso <= parts[1] <= end_iso:
            items.append(row)
    return items


def _avg(values: Iterable[float]) -> float | None:
    """Średnia arytmetyczna; None gdy lista pusta (caller zostawia field
    `None` w `TodayState` — frontend pokazuje "—")."""
    seq = list(values)
    if not seq:
        return None
    return sum(seq) / len(seq)


def _query_hrv_24h(user_id: str, *, today: date) -> float | None:
    """Średnia HRV (ms) z ostatnich 24h — multipoint metric, SK:
    `BIOMETRY#{date}#hrv#{ts}`. Zbieramy z `today` i `today-1` (HAE wysyła
    z lokalną datą, granica doby może odciąć ostatnie pomiary).

    Frontend ma swoją logikę agregacji per okno; advisor potrzebuje
    pojedynczy `float` jako wskaźnik, więc tu spłaszczamy.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    values: list[float] = []
    for day in (today - timedelta(days=1), today):
        items = query_by_pk(f"USER#{user_id}", sk_prefix=f"BIOMETRY#{day.isoformat()}#hrv#")
        for item in items:
            recorded_at_raw = item.get("recorded_at")
            if not isinstance(recorded_at_raw, str):
                continue
            try:
                recorded_at = datetime.fromisoformat(recorded_at_raw)
            except ValueError:
                continue
            if recorded_at < cutoff:
                continue
            value = item.get("value_ms")
            if value is None:
                continue
            values.append(_decimal_to_float(value))
    return _avg(values)


def _load_profile_targets(user_id: str) -> tuple[int, int, int, int]:
    """Read `kcal_target`/`protein_target_g`/`fat_target_g`/`carbs_target_g`
    z PROFILE row. Fallback hardcoded defaults z log warning gdy brak/missing.

    Preferowany fallback nad 503 (UX > strict). Owner może wpisać atrybuty
    manualnie via DDB UpdateItem post-deploy.
    """
    profile = get_item(f"USER#{user_id}", "PROFILE")
    if profile is None:
        logger.warning(
            "profile_missing_default_targets",
            extra={"user_id": user_id, "handler": "advisor_chat"},
        )
        return (
            DEFAULT_KCAL_TARGET,
            DEFAULT_PROTEIN_TARGET_G,
            DEFAULT_FAT_TARGET_G,
            DEFAULT_CARBS_TARGET_G,
        )
    kcal_target = profile.get("kcal_target")
    protein_target = profile.get("protein_target_g")
    fat_target = profile.get("fat_target_g")
    carbs_target = profile.get("carbs_target_g")
    if kcal_target is None or protein_target is None:
        logger.warning(
            "profile_targets_default",
            extra={
                "user_id": user_id,
                "handler": "advisor_chat",
                "has_kcal_target": kcal_target is not None,
                "has_protein_target": protein_target is not None,
            },
        )
    return (
        int(kcal_target) if kcal_target is not None else DEFAULT_KCAL_TARGET,
        int(protein_target) if protein_target is not None else DEFAULT_PROTEIN_TARGET_G,
        int(fat_target) if fat_target is not None else DEFAULT_FAT_TARGET_G,
        int(carbs_target) if carbs_target is not None else DEFAULT_CARBS_TARGET_G,
    )


def build_today_state(user_id: str, today: date) -> TodayState:
    """Zbierz kontekst dzisiejszych metryk dla LLM.

    Cumulative (kcal_*, protein, steps) → `sum_metric_today` (sum hourly
    bucketów). Snapshoty (weight) → 7d trend z `_query_snapshots_in_range`.
    Recovery proxies (sleep, HRV, resting_hr) → snapshot ostatniej nocy /
    24h average / 7d average.

    Wszystkie wartości None-safe — brak DDB rows daje sensowne defaults
    (kcal_consumed=0, weight_kg=None) bez crash.
    """
    # Cumulative sums for today.
    kcal_consumed = _decimal_to_float(
        sum_metric_today(user_id, "kcal_in", value_attr="kcal", today=today)
    )
    kcal_active = _decimal_to_float(
        sum_metric_today(user_id, "kcal_active", value_attr="kcal", today=today)
    )
    kcal_basal = _decimal_to_float(
        sum_metric_today(user_id, "kcal_basal", value_attr="kcal", today=today)
    )
    protein_consumed = _decimal_to_float(
        sum_metric_today(user_id, "protein", value_attr="g", today=today)
    )
    step_count_raw = sum_metric_today(user_id, "steps", value_attr="count", today=today)
    step_count = int(step_count_raw)

    # Targets z PROFILE (fallback defaults).
    kcal_target, protein_target_g, fat_target_g, carbs_target_g = _load_profile_targets(user_id)

    # Weight today + 7d avg (snapshot, jeden item per dzień).
    weight_today_items = _query_snapshots_in_range(user_id, "weight", start=today, end=today)
    weight_kg_today = (
        _decimal_to_float(weight_today_items[0].get("kg")) if weight_today_items else None
    )
    weight_7d_items = _query_snapshots_in_range(
        user_id, "weight", start=today - timedelta(days=6), end=today
    )
    weight_kg_7d_avg = _avg(_decimal_to_float(item.get("kg")) for item in weight_7d_items)

    # Sleep last night (sleep snapshot z `today` lub `today-1` — HAE wysyła
    # po przebudzeniu z datą lokalną zwykle = today albo today-1 zależnie
    # od godziny wysyłki). Bierzemy najnowszy dostępny (preferuj today).
    sleep_items = _query_snapshots_in_range(
        user_id, "sleep", start=today - timedelta(days=1), end=today
    )
    sleep_hours_last_night: float | None = None
    if sleep_items:
        # Preferuj najnowszy = ostatni z zwracanej listy (range jest rosnąco).
        latest = sleep_items[-1]
        asleep = latest.get("asleep")
        if asleep is not None:
            sleep_hours_last_night = _decimal_to_float(asleep)

    # HRV 24h average (multipoint).
    hrv_sdnn_24h_avg = _query_hrv_24h(user_id, today=today)

    # Resting HR 7d avg (snapshot).
    rhr_items = _query_snapshots_in_range(
        user_id, "resting_hr", start=today - timedelta(days=6), end=today
    )
    resting_hr_7d_avg = _avg(_decimal_to_float(item.get("bpm")) for item in rhr_items)

    kcal_remaining = float(kcal_target) - kcal_consumed

    return TodayState(
        kcal_consumed=round(kcal_consumed, 1),
        kcal_active=round(kcal_active, 1),
        kcal_basal=round(kcal_basal, 1),
        kcal_target=kcal_target,
        kcal_remaining=round(kcal_remaining, 1),
        protein_consumed_g=round(protein_consumed, 1),
        protein_target_g=protein_target_g,
        fat_target_g=fat_target_g,
        carbs_target_g=carbs_target_g,
        step_count=step_count,
        weight_kg_today=round(weight_kg_today, 2) if weight_kg_today is not None else None,
        weight_kg_7d_avg=(round(weight_kg_7d_avg, 2) if weight_kg_7d_avg is not None else None),
        sleep_hours_last_night=(
            round(sleep_hours_last_night, 2) if sleep_hours_last_night is not None else None
        ),
        hrv_sdnn_24h_avg=(round(hrv_sdnn_24h_avg, 1) if hrv_sdnn_24h_avg is not None else None),
        resting_hr_7d_avg=(round(resting_hr_7d_avg, 1) if resting_hr_7d_avg is not None else None),
    )


# ─── Chat history (DDB CHAT#{date}#{turn_idx:04d}) ─────────────────────────


def _now_iso() -> str:
    """Test seam — pozwala mockować ISO timestamp w testach."""
    return datetime.now(UTC).isoformat()


def _now_epoch() -> int:
    """Test seam — pozwala mockować unix epoch w testach."""
    return int(time.time())


def read_history(user_id: str, today: date) -> list[ChatMessage]:
    """Read all chat turns dla `today` (UTC) z DDB.

    Query: `PK=USER#{user_id} AND begins_with(SK, "CHAT#{today}#")`.
    Items zwracane DDB-default ascending order (po SK), więc rosnąco po
    `turn_idx` — gotowe do wstawienia w prompt jak "turn 0, 1, 2, ...".

    Pusta lista gdy brak rozmów dziś.
    """
    sk_prefix = f"CHAT#{today.isoformat()}#"
    rows = query_by_pk(f"USER#{user_id}", sk_prefix=sk_prefix)
    messages: list[ChatMessage] = []
    for row in rows:
        sk = row.get("SK", "")
        parts = sk.split("#")
        # SK: "CHAT#YYYY-MM-DD#NNNN" — 3 części.
        if len(parts) != 3:
            continue
        try:
            turn_idx = int(parts[2])
        except ValueError:
            continue
        role = row.get("role")
        content = row.get("content")
        ts = row.get("ts")
        if role not in ("user", "assistant"):
            continue
        if not isinstance(content, str) or not isinstance(ts, str):
            continue
        messages.append(ChatMessage(role=role, content=content, turn_idx=turn_idx, ts=ts))
    return messages


def count_today_turns(user_id: str, today: date) -> int:
    """Liczba USER turns dziś (assistant turns nie liczą się do rate limitu).

    Implementacja MVP: `len(read_history)` + filter po roli. Optymalizacja
    (np. dedicated `count_by_pk` w `shared/dynamo.py` lub atomic counter)
    do reviewer/architect jeśli reviewer kwestionuje koszty RCU. Cap dzienny
    30 user turns ⇒ max 60 items czytane — pomijalne (~1 RCU per Query).
    """
    history = read_history(user_id, today)
    return sum(1 for m in history if m.role == "user")


def append_message(
    user_id: str,
    today: date,
    role: str,
    content: str,
    *,
    tokens_used: dict[str, int] | None = None,
) -> int:
    """Zapisz turę do DDB z auto-incremented `turn_idx`.

    `turn_idx = max(existing) + 1`, lub 0 gdy historia pusta. Build SK jako
    `CHAT#{today}#{turn_idx:04d}` (zero-padded 4-cyfry — sortable lexico
    do 9999 tur, sensible upper bound).

    `tokens_used` (z Anthropic usage) zapisywane tylko dla assistant turn —
    przydatne dla replay/debug. User turn ma `None`.

    Returns assigned `turn_idx`.
    """
    history = read_history(user_id, today)
    next_idx = max((m.turn_idx for m in history), default=-1) + 1
    sk = f"CHAT#{today.isoformat()}#{next_idx:04d}"
    attrs: dict[str, Any] = {
        "role": role,
        "content": content,
        "ts": _now_iso(),
        "ttl": _now_epoch() + CHAT_TTL_SECONDS,
    }
    if tokens_used is not None:
        attrs["tokens_used"] = tokens_used
    put_item(f"USER#{user_id}", sk, attrs)
    return next_idx


# ─── Prompt composition ────────────────────────────────────────────────────


def build_chat_messages(
    history: list[ChatMessage],
    today_state: TodayState,
    user_message: str,
) -> list[dict[str, Any]]:
    """Buduje pojedynczy user message z 3 (PR2: 4) blokami XML-ish:
    `<conversation_history>`, `<today_context>`, `<user_message>`.

    Per ADR-007 D7: pojedynczy user message do Anthropic (NIE native
    multi-turn `messages=[{role:user},{role:assistant},...]`) — daje
    stabilny prompt cache (system prompt cached osobno via `cache_control`).

    Hard cap 20 ostatnich tur historii (drop oldest) — chroni token budget.
    """
    recent = history[-RECENT_HISTORY_LIMIT:]
    history_text = "\n".join(f"turn {m.turn_idx} [{m.role}]: {m.content}" for m in recent)
    today_state_json = today_state.model_dump_json(indent=2)

    # TODO(PR2): wstaw <retrieved_recipes>...</retrieved_recipes> block z RAG retrieval

    composed = (
        "<conversation_history>\n"
        f"{history_text}\n"
        "</conversation_history>\n"
        "\n"
        "<today_context>\n"
        f"{today_state_json}\n"
        "</today_context>\n"
        "\n"
        "<user_message>\n"
        f"{user_message}\n"
        "</user_message>"
    )
    return [{"role": "user", "content": composed}]


# ─── Anthropic call ────────────────────────────────────────────────────────


def call_chat(
    system_prompt: str,
    messages: list[dict[str, Any]],
) -> tuple[str, TokenUsage]:
    """Wywołaj Anthropic Haiku z system prompt (cached) + free-form messages.

    NO `tools` / `tool_choice` (per ADR-007 D6 — chat zwraca plain text,
    nie structured tool_use jak dinner advisor).

    Returns `(text, token_usage)`. Emituje `logger.info("anthropic_call", ...)`
    z usage breakdown dla CloudWatch metric filter (cost guard alarm).
    Log shape MUST stay identical do PR #50 — pattern parsowany przez
    `cloudwatch.tf` aws_cloudwatch_log_metric_filter.

    Raise:
      `AdvisorUnavailableError` — SSM key missing/placeholder.
      `AdvisorBackendError` — Anthropic 5xx / timeout / unexpected response shape.
    """
    client = get_anthropic_client()

    # Lazy import — Anthropic SDK exception types tylko w prod path.
    from anthropic import APIConnectionError, APIStatusError, APITimeoutError
    from anthropic.types import MessageParam

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=cast("list[MessageParam]", messages),
        )
    except (APIStatusError, APIConnectionError, APITimeoutError) as exc:
        # Anthropic SDK ma built-in retry (max_retries=2 w client init).
        # Po wyczerpaniu rzuca te exceptions — handler zwraca 503.
        raise AdvisorBackendError(f"anthropic_api_error: {exc}") from exc

    # Free-form text response — first content block must be type=text.
    content_blocks = response.content
    if not content_blocks:
        raise AdvisorBackendError("anthropic_empty_content")
    first = content_blocks[0]
    if getattr(first, "type", None) != "text":
        raise AdvisorBackendError(f"anthropic_unexpected_block_type: {getattr(first, 'type', '?')}")
    text = getattr(first, "text", None)
    if not isinstance(text, str):
        raise AdvisorBackendError("anthropic_text_block_missing_text")

    usage = response.usage
    token_usage = TokenUsage(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        cache_read_input_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        cache_creation_input_tokens=int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
    )

    # Structured log — log shape MUST match PR #50 dla CloudWatch metric filter.
    logger.info(
        "anthropic_call",
        extra={
            "input_tokens": token_usage.input_tokens,
            "output_tokens": token_usage.output_tokens,
            "cache_read_input_tokens": token_usage.cache_read_input_tokens,
            "cache_creation_input_tokens": token_usage.cache_creation_input_tokens,
            "model": MODEL,
        },
    )
    return text, token_usage


# Re-export lista shortów dla referencji testów/handlera.
__all__ = [
    "ANTHROPIC_API_KEY_PARAM",
    "AdvisorBackendError",
    "AdvisorUnavailableError",
    "DEFAULT_KCAL_TARGET",
    "MAX_TOKENS",
    "MODEL",
    "RECENT_HISTORY_LIMIT",
    "_CUMULATIVE_VALUE_ATTRS",
    "_SYSTEM_PROMPT",
    "append_message",
    "build_chat_messages",
    "build_today_state",
    "call_chat",
    "count_today_turns",
    "get_anthropic_client",
    "read_history",
]
