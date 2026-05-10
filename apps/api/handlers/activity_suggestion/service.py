"""Service layer dla activity_suggestion (Sprint 10 A0.5).

Flow per call:
1. `gather_activity_context(user_id, today)` — query DDB ACTIVITY + BIOMETRY
   last 7d, agreguj liczby (count per sport_type, totals, daily averages),
   formatuj jako text block dla LLM.
2. `call_anthropic_for_activity_level(context_text)` — Anthropic Haiku call
   z prompt cached system prompt → JSON output parsed via Pydantic. Retry
   raz przy malformed JSON (LLM occasionally adds prose before JSON).

Anthropic SDK + system prompt cache pattern z advisor_chat (PR #50/#62).
Log shape `anthropic_call` MUSI matchować `cloudwatch.tf` metric filter
żeby cost-guard alarm dalej działał — to jest shared CloudWatch metric.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from pydantic import ValidationError

from handlers.activity_suggestion.schemas import ActivitySuggestion
from shared.dynamo import query_by_pk, sum_metric_in_range
from shared.logging import get_logger
from shared.ssm import SecretMisconfiguredError, load_secure_secret

logger = get_logger("activity_suggestion")

# Anthropic constants — match advisor_chat per ADR-007 D7 (single model
# across all LLM endpointów dla cost predictability i prompt cache reuse).
ANTHROPIC_API_KEY_PARAM = "/bodysync/anthropic/api_key"
ANTHROPIC_API_KEY_MIN_LENGTH = 50
MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 512  # JSON output ~150 tokens; bufor na reasoning expansion

# System prompt loaded once per cold start (file read w module init).
_SYSTEM_PROMPT_PATH = Path(__file__).parent / "system_prompt.txt"
_SYSTEM_PROMPT: str = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

# Lookback window — match Mifflin-St Jeor activity multiplier semantics
# (multiplier reprezentuje typowy tydzień, nie miesięczny avg).
LOOKBACK_DAYS = 7


class ActivitySuggestionUnavailableError(Exception):
    """SSM Anthropic key missing/PLACEHOLDER → handler 503."""


class ActivitySuggestionBackendError(Exception):
    """Anthropic 5xx, timeout, malformed JSON output → handler 502.

    `reason` to fixed-vocabulary code (NIE Anthropic exception message)
    żeby nie leakować response body do logów.
    """

    def __init__(self, reason: str, *, status_code: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


_anthropic_client: Anthropic | None = None


def get_anthropic_client() -> Anthropic:
    """Lazy singleton — pierwszy call Anthropic w cold start tworzy client.

    Cold start cost ~50ms (httpx + ssl). Cache w module global przeżywa
    container freeze.
    """
    global _anthropic_client
    if _anthropic_client is not None:
        return _anthropic_client

    try:
        api_key = load_secure_secret(
            ANTHROPIC_API_KEY_PARAM, min_length=ANTHROPIC_API_KEY_MIN_LENGTH
        )
    except SecretMisconfiguredError as e:
        raise ActivitySuggestionUnavailableError("anthropic_key_misconfigured") from e

    _anthropic_client = Anthropic(api_key=api_key, max_retries=2)
    return _anthropic_client


def _reset_client_for_tests() -> None:
    """Test-only — drop module client cache between fixtures."""
    global _anthropic_client
    _anthropic_client = None


def gather_activity_context(user_id: str, today: date) -> tuple[str, dict[str, Any]]:
    """Query DDB last 7d activities + biometry, format jako LLM text block.

    Returns:
      (context_text, summary_dict) — context_text idzie do LLM prompt,
      summary_dict zwracamy w response (frontend pokazuje "4 treningi,
      avg 8200 kroków" obok reasoning).
    """
    end = today
    start = today - timedelta(days=LOOKBACK_DAYS - 1)
    cutoff_iso = start.isoformat()

    # Strava activities — pobieramy wszystkie i filtrujemy po start_date.
    # Typowy user ma <500 activities total → 1 Query OK.
    rows = query_by_pk(f"USER#{user_id}", sk_prefix="ACTIVITY#")
    recent = [r for r in rows if str(r.get("start_date", "")) >= cutoff_iso]

    # Aggregate per sport_type (Run / Ride / Walk / etc.).
    sport_counts: dict[str, int] = {}
    sport_distances: dict[str, float] = {}
    total_duration_s = 0.0
    for r in recent:
        sport = str(r.get("sport_type") or "Other")
        sport_counts[sport] = sport_counts.get(sport, 0) + 1
        dist = float(str(r.get("distance_m") or 0))
        sport_distances[sport] = sport_distances.get(sport, 0.0) + dist
        total_duration_s += float(str(r.get("moving_time_s") or 0))

    # Biometry: per-day sum dla cumulative metryk (steps, kcal_active).
    # `sum_metric_in_range` zwraca dict[date, Decimal] — averagujemy po
    # dniach z entry (brak fill-zero dla dni bez danych — daje true avg).
    steps_per_day = sum_metric_in_range(user_id, "steps", value_attr="count", start=start, end=end)
    kcal_active_per_day = sum_metric_in_range(
        user_id, "kcal_active", value_attr="kcal", start=start, end=end
    )

    # `sum_metric_in_range` zwraca wpisy dla WSZYSTKICH dni w przedziale —
    # dni bez HAE data mają Decimal("0"). Filter na non-zero dla "real avg":
    # dzień z 0 kroków = brak telefonu / no HAE webhook, nie real-world 0.
    non_zero_steps = [int(v) for v in steps_per_day.values() if int(v) > 0]
    non_zero_kcal = [int(v) for v in kcal_active_per_day.values() if int(v) > 0]
    avg_steps = int(sum(non_zero_steps) / len(non_zero_steps)) if non_zero_steps else None
    avg_kcal_active = int(sum(non_zero_kcal) / len(non_zero_kcal)) if non_zero_kcal else None
    days_with_steps = len(non_zero_steps)

    # Build text block — kompaktowy, polski, no PII.
    lines = [
        f"Tydzień {start.isoformat()}..{end.isoformat()} (7 dni):",
        "",
        f"Treningi (Strava): {len(recent)} aktywności",
    ]
    if recent:
        for sport, count in sorted(sport_counts.items(), key=lambda x: -x[1]):
            km = sport_distances[sport] / 1000
            lines.append(f"- {sport}: {count}× ({km:.1f} km)")
        total_km = sum(sport_distances.values()) / 1000
        total_h = total_duration_s / 3600
        lines.append(f"- Łącznie: {total_km:.1f} km, {total_h:.1f}h ruchu")
    else:
        lines.append("- (brak)")

    lines.append("")
    lines.append("Dzienne (Apple Health):")
    if avg_steps is not None:
        lines.append(f"- Średnio {avg_steps} kroków/dzień ({days_with_steps}/7 dni z danymi)")
    else:
        lines.append("- Brak danych o krokach")
    if avg_kcal_active is not None:
        lines.append(f"- Średnio {avg_kcal_active} kcal aktywnych/dzień")
    else:
        lines.append("- Brak danych o kcal aktywnych")

    context_text = "\n".join(lines)
    summary: dict[str, Any] = {
        "activities_count": len(recent),
        "avg_steps": avg_steps,
        "avg_kcal_active": avg_kcal_active,
    }
    return context_text, summary


def _extract_json(text: str) -> str:
    """LLM occasionally wraps JSON w prose ("Oto wynik: {...}") lub markdown
    code fence (```json ... ```). Wytnij pierwszy `{...}` block.
    """
    # Strip markdown fence
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1)
    # Find first {...} balanced block (assumes well-formed)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def call_anthropic_for_activity_level(context_text: str) -> ActivitySuggestion:
    """Anthropic Haiku call z prompt cache + JSON output parse.

    System prompt cached (`cache_control: ephemeral`) — cold call ~$0.001,
    warm <$0.0002. User message: kontekst z gather_activity_context.

    Raise:
      `ActivitySuggestionUnavailableError` — SSM key missing.
      `ActivitySuggestionBackendError` — Anthropic 5xx / timeout / JSON parse fail.
    """
    client = get_anthropic_client()

    # Lazy import — Anthropic SDK exception types tylko w prod path.
    from anthropic import APIConnectionError, APIStatusError, APITimeoutError
    from anthropic.types import MessageParam

    user_message = (
        f"<activity_context>\n{context_text}\n</activity_context>\n\n"
        "Oceń poziom aktywności dziennej w skali 5-poziomowej. "
        "Zwróć tylko JSON {level, reasoning} bez innego tekstu."
    )

    messages: list[MessageParam] = [{"role": "user", "content": user_message}]

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=messages,
        )
    except APIStatusError as exc:
        raise ActivitySuggestionBackendError(
            "api_status_error", status_code=getattr(exc, "status_code", None)
        ) from exc
    except APITimeoutError as exc:
        raise ActivitySuggestionBackendError("api_timeout") from exc
    except APIConnectionError as exc:
        raise ActivitySuggestionBackendError("api_connection_error") from exc

    content_blocks = response.content
    if not content_blocks:
        raise ActivitySuggestionBackendError("empty_content")
    first = content_blocks[0]
    if getattr(first, "type", None) != "text":
        raise ActivitySuggestionBackendError("unexpected_block_type")
    text = getattr(first, "text", None)
    if not isinstance(text, str):
        raise ActivitySuggestionBackendError("text_block_missing_text")

    # Log usage — match shape z advisor_chat (CloudWatch metric filter
    # `anthropic_call` jest shared dla cost-guard alarm).
    usage = response.usage
    logger.info(
        "anthropic_call",
        extra={
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            "cache_read_input_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            "cache_creation_input_tokens": int(
                getattr(usage, "cache_creation_input_tokens", 0) or 0
            ),
            "model": MODEL,
        },
    )

    # Parse JSON output. Retry raz po extracting w razie LLM prose wrap.
    json_text = _extract_json(text)
    try:
        parsed = json.loads(json_text)
    except json.JSONDecodeError as e:
        logger.warning(
            "llm_json_parse_failed",
            extra={"reason": "json_decode_error", "exc_type": type(e).__name__},
        )
        raise ActivitySuggestionBackendError("json_parse_failed") from e

    try:
        return ActivitySuggestion.model_validate(parsed)
    except ValidationError as e:
        logger.warning(
            "llm_schema_validation_failed",
            extra={"reason": "schema_validation_error"},
        )
        raise ActivitySuggestionBackendError("schema_validation_failed") from e


__all__ = [
    "ANTHROPIC_API_KEY_PARAM",
    "LOOKBACK_DAYS",
    "MODEL",
    "ActivitySuggestionBackendError",
    "ActivitySuggestionUnavailableError",
    "_reset_client_for_tests",
    "call_anthropic_for_activity_level",
    "gather_activity_context",
    "get_anthropic_client",
]
