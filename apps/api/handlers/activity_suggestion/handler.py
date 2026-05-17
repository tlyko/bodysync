"""AWS Lambda entrypoint dla `POST /api/profile/suggest-activity-level` (Sprint 10 A0.5).

LLM-driven activity level detection dla TDEE wizard. User klika button
"Sugestia z mojej aktywności" → handler zbiera 7d Strava + biometry,
Anthropic Haiku ocenia poziom (sedentary/light/moderate/heavy/athlete)
+ generuje 1-3 zdaniowe reasoning po polsku.

Frontend pre-selectuje activity_level w wizardzie + pokazuje reasoning;
user może override (LLM jest podpowiedzią, nie autorytetem).

Status codes:
- 200 OK + JSON ActivitySuggestionResponse
- 401 Unauthorized — brak / niepoprawny JWT
- 502 Bad Gateway — LLM JSON malformed lub Anthropic 5xx
- 503 Service Unavailable — Anthropic key missing (PLACEHOLDER)
- 500 Internal Server Error — catch-all (logged with traceback)

NO content logging — tylko `level`, `activities_count`, token counts.
Reasoning content (po polsku, generowane LLM) NIE leci do CloudWatch.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from handlers.activity_suggestion.schemas import ActivitySuggestionResponse
from handlers.activity_suggestion.service import (
    ActivitySuggestionBackendError,
    ActivitySuggestionUnavailableError,
    call_anthropic_for_activity_level,
    gather_activity_context,
)
from shared.auth import AuthError, verify_jwt
from shared.csrf import CSRFError, verify_csrf
from shared.http import extract_session_cookie, response
from shared.logging import get_logger

logger = get_logger("activity_suggestion")

WARSAW_TZ = ZoneInfo("Europe/Warsaw")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "local")

    token = extract_session_cookie(event)
    if not token:
        logger.info("missing_session", extra={"request_id": request_id})
        return response(401, {"error": "missing session cookie"})

    try:
        payload = verify_jwt(token)
    except AuthError as e:
        logger.info(
            "invalid_session",
            extra={"request_id": request_id, "reason": str(e)},
        )
        return response(401, {"error": "invalid session"})

    user_id = payload.get("user_id")
    if not user_id:
        return response(401, {"error": "user_id missing in jwt"})

    # CSRF guard (sec audit 2026-05-16 P1-4) — endpoint pala LLM call ($).
    try:
        verify_csrf(event)
    except CSRFError:
        logger.info("csrf_failed", extra={"request_id": request_id, "user_id": user_id})
        return response(403, {"error": "csrf_required"})

    # Today w Europe/Warsaw — match advisor_chat semantics. 7d window
    # liczone od jego północy do dziś rano.
    today = datetime.now(UTC).astimezone(WARSAW_TZ).date()

    try:
        context_text, summary = gather_activity_context(user_id, today)
        suggestion = call_anthropic_for_activity_level(context_text)
    except ActivitySuggestionUnavailableError as e:
        logger.warning(
            "anthropic_unavailable",
            extra={
                "request_id": request_id,
                "user_id": user_id,
                "reason": str(e),
            },
        )
        return response(503, {"error": "advisor_unavailable", "reason": str(e)})
    except ActivitySuggestionBackendError as e:
        logger.warning(
            "llm_backend_error",
            extra={
                "request_id": request_id,
                "user_id": user_id,
                "reason": e.reason,
                "status_code": e.status_code,
            },
        )
        return response(502, {"error": "advisor_backend_error", "reason": e.reason})
    except Exception:
        logger.exception("internal_error", extra={"request_id": request_id})
        return response(500, {"error": "internal"})

    result = ActivitySuggestionResponse(
        level=suggestion.level,
        reasoning=suggestion.reasoning,
        activities_count=summary["activities_count"],
        avg_steps=summary["avg_steps"],
        avg_kcal_active=summary["avg_kcal_active"],
    )
    logger.info(
        "activity_level_suggested",
        extra={
            "request_id": request_id,
            "user_id": user_id,
            "level": suggestion.level,
            "activities_count": summary["activities_count"],
        },
    )
    return response(200, result.model_dump())
