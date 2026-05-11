"""LLM Haiku narrative dla diet check (Sprint 11.5 PR2 per ADR-009).

Anthropic Haiku 4.5 z `cache_control: ephemeral` system prompt (~2KB
cached przez 5min). Per-call user message structured z deterministic
liczbami z `DietCheckResult`. Output max 200 tokens, hard truncate
do 400 chars (system prompt już to wymusza, defense in depth).

Graceful degradation: każdy SDK error / timeout / network → return
None + log warning. Handler ustawia `narrative_unavailable=True`,
frontend pokazuje raw status + "Szczegóły" (algorithm wartości).
NIE blokuje persist `diet_check_history` — owner ma przynajmniej
deterministic data.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from handlers.tdee_recalc.schemas import DietCheckResult
from shared.logging import get_logger
from shared.ssm import SecretMisconfiguredError, load_secure_secret

if TYPE_CHECKING:
    from anthropic import Anthropic

logger = get_logger("tdee_recalc")

ANTHROPIC_API_KEY_PARAM = "/bodysync/anthropic/api_key"
ANTHROPIC_API_KEY_MIN_LENGTH = 50

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 200  # Cap output ~150 słów PL.
NARRATIVE_HARD_LIMIT = 400  # Truncate gdy LLM ignoruje instrukcję 400 chars.

_SYSTEM_PROMPT_PATH = Path(__file__).parent / "system_prompt.txt"
_SYSTEM_PROMPT: str = _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

_anthropic_client: Anthropic | None = None


def _get_anthropic_client() -> Anthropic | None:
    """Lazy singleton — None gdy SSM key missing/placeholder/SSM down/etc.

    Graceful degradation: każdy fail (SSM ParameterNotFound, IAM denied,
    SecretMisconfiguredError, network) → None → caller (handler) ustawia
    `narrative_unavailable=True`, persist mimo to. Diet check jest non-critical
    (deterministic stats nadal działają), narrative to bonus.
    """
    global _anthropic_client
    if _anthropic_client is not None:
        return _anthropic_client
    try:
        api_key = load_secure_secret(
            ANTHROPIC_API_KEY_PARAM, min_length=ANTHROPIC_API_KEY_MIN_LENGTH
        )
    except SecretMisconfiguredError:
        logger.warning("anthropic_api_key_missing", extra={"handler": "tdee_recalc"})
        return None
    except Exception as exc:
        # Broad catch — SSM ParameterNotFound (boto3.errorfactory), IAM,
        # network, etc. Diet check non-critical, log + continue z None.
        logger.warning(
            "anthropic_api_key_load_failed",
            extra={"handler": "tdee_recalc", "exc_type": type(exc).__name__},
        )
        return None
    from anthropic import Anthropic

    _anthropic_client = Anthropic(api_key=api_key, max_retries=2)
    return _anthropic_client


def _reset_client_for_tests() -> None:
    """Test-only — drop singleton between tests."""
    global _anthropic_client
    _anthropic_client = None


def _build_user_message(result: DietCheckResult) -> str:
    """Strukturalna treść `<diet_check_data>` block dla LLM.

    Trzyma się rygoru: tylko liczby z `result`, nigdy guess. Status hint
    jako string (LLM dostosowuje narrative tone).
    """
    return (
        "<diet_check_data>\n"
        f"goal_kcal: {result.goal_kcal}\n"
        f"kcal_in_avg: {result.kcal_in_avg}\n"
        f"waga_then_kg: {result.waga_then_kg}\n"
        f"waga_now_kg: {result.waga_now_kg}\n"
        f"waga_delta_kg: {result.waga_delta_kg}\n"
        f"expected_delta_kg: {result.expected_delta_kg}\n"
        f"actual_delta_kg: {result.actual_delta_kg}\n"
        f"diff_kg: {result.diff_kg}\n"
        f"status: {result.status}\n"
        "</diet_check_data>\n\n"
        "Napisz narrację po polsku zgodnie z formatem z system prompt."
    )


def generate_narrative(result: DietCheckResult) -> str | None:
    """Wywołaj Haiku z deterministic stats → zwróć narrative (str) lub None.

    None oznacza graceful degradation — caller (handler) ustawia
    `narrative_unavailable=True`, persist mimo to (history zachowuje
    deterministic data + flag że LLM był wyłączony tym razem).

    NIE wywołuj dla `result.skipped=True` — caller powinien skip.
    """
    if result.skipped:
        return None  # Defensive — skip results nie powinny dolatywać tu.

    client = _get_anthropic_client()
    if client is None:
        return None

    from anthropic import APIConnectionError, APIStatusError, APITimeoutError

    user_message = _build_user_message(result)

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
            messages=[{"role": "user", "content": user_message}],
        )
    except (APIStatusError, APITimeoutError, APIConnectionError) as exc:
        logger.warning(
            "llm_call_failed",
            extra={
                "handler": "tdee_recalc",
                "exc_type": type(exc).__name__,
                "status_code": getattr(exc, "status_code", None),
            },
        )
        return None

    blocks = response.content
    if not blocks or getattr(blocks[0], "type", None) != "text":
        logger.warning("llm_unexpected_block_type", extra={"handler": "tdee_recalc"})
        return None

    text = getattr(blocks[0], "text", None)
    if not isinstance(text, str) or not text.strip():
        return None

    # Hard truncate defense — system prompt mówi 400 chars, ale Haiku
    # czasami przekracza. Lepszy ucięty tekst niż wybijający z UI layoutu.
    narrative = text.strip()
    if len(narrative) > NARRATIVE_HARD_LIMIT:
        narrative = narrative[: NARRATIVE_HARD_LIMIT - 1].rstrip() + "…"

    usage = response.usage
    logger.info(
        "anthropic_call",
        extra={
            "handler": "tdee_recalc",
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            "cache_read_input_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            "cache_creation_input_tokens": int(
                getattr(usage, "cache_creation_input_tokens", 0) or 0
            ),
            "model": MODEL,
        },
    )
    return narrative
