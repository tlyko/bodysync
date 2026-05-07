"""AWS Lambda entrypoint dla `POST /api/advisor/dinner` (Sprint 6 MVP).

Per ADR-006:
1. JWT cookie verify (`bodysync_session`, set przez google_auth handler)
2. Pydantic parse `DinnerAdvisorRequest` z body
3. Query param `force` (boolean, bypass cache 1h)
4. `today = datetime.now(Europe/Warsaw).date()` — user lokalna data
5. `service.get_cached_or_call` zwraca response + cache_hit + usage_dict
6. Structured log z `request_id`, `user_id`, `cache_hit`, tokens dla cost guard

Status codes:
- 200 OK + JSON `DinnerAdvisorResponse`
- 400 Bad Request — invalid JSON / Pydantic ValidationError
- 401 Unauthorized — brak / niepoprawny JWT
- 503 Service Unavailable — Anthropic key missing (PLACEHOLDER) lub Anthropic 5xx
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from handlers.advisor_dinner.schemas import DinnerAdvisorRequest
from handlers.advisor_dinner.service import (
    AdvisorBackendError,
    AdvisorUnavailableError,
    get_cached_or_call,
)
from shared.auth import AuthError, verify_jwt
from shared.logging import get_logger

logger = get_logger("advisor_dinner")

COOKIE_NAME = "bodysync_session"
WARSAW_TZ = ZoneInfo("Europe/Warsaw")


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def _extract_session_cookie(event: dict[str, Any]) -> str | None:
    """Mirror api_read._extract_session_cookie — API GW HTTP API v2 daje
    `cookies: list[str]` w event payload, fallback na `Cookie` header."""
    cookies: list[str] = event.get("cookies") or []
    for cookie in cookies:
        if cookie.startswith(f"{COOKIE_NAME}="):
            return cookie.split("=", 1)[1]
    headers: dict[str, str] = event.get("headers") or {}
    raw: str | None = headers.get("cookie") or headers.get("Cookie")
    if raw:
        for part in raw.split(";"):
            stripped = part.strip()
            if stripped.startswith(f"{COOKIE_NAME}="):
                return stripped.split("=", 1)[1]
    return None


def _parse_force_flag(event: dict[str, Any]) -> bool:
    """Query string `?force=true` lub body field `force=true`. Default False.

    HTTP API v2 daje `queryStringParameters: dict[str,str] | None`. Wartości
    case-insensitive `true/1` traktujemy jako True.
    """
    qs = event.get("queryStringParameters") or {}
    raw = qs.get("force")
    if raw is None:
        return False
    return raw.strip().lower() in ("true", "1", "yes")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "local")

    token = _extract_session_cookie(event)
    if not token:
        logger.info("missing_session", extra={"request_id": request_id})
        return _response(401, {"error": "missing session cookie"})
    try:
        payload = verify_jwt(token)
    except AuthError:
        logger.info("invalid_session", extra={"request_id": request_id})
        return _response(401, {"error": "invalid session"})
    user_id = payload.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        logger.warning("session_no_user_id", extra={"request_id": request_id})
        return _response(401, {"error": "invalid session payload"})

    raw_body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64

        raw_body = base64.b64decode(raw_body).decode("utf-8")
    # Empty body → empty notes; allow {} dla simple POST.
    if not raw_body.strip():
        raw_body = "{}"
    try:
        body_dict = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning("invalid_json", extra={"request_id": request_id, "user_id": user_id})
        return _response(400, {"error": "invalid json body"})

    try:
        req = DinnerAdvisorRequest.model_validate(body_dict)
    except ValidationError as exc:
        # Sanityzacja per CLAUDE.md "bez payloadu w logach" — sample point's
        # raw input nie wraca do logów ani body response.
        sanitized = [{"loc": err["loc"], "type": err["type"]} for err in exc.errors()]
        logger.warning("invalid_payload", extra={"request_id": request_id, "user_id": user_id})
        return _response(400, {"error": "invalid payload", "details": sanitized})

    force = _parse_force_flag(event)
    today = datetime.now(WARSAW_TZ).date()

    try:
        response, cache_hit, usage = get_cached_or_call(
            user_id, today, force=force, notes=req.notes
        )
    except AdvisorUnavailableError:
        logger.warning(
            "advisor_api_key_missing",
            extra={"request_id": request_id, "user_id": user_id, "reason": "api_key_missing"},
        )
        return _response(503, {"error": "advisor unavailable", "reason": "api_key_missing"})
    except AdvisorBackendError:
        # `exception` log emituje stacktrace — nie payload, tylko exception
        # message + traceback. Per CLAUDE.md "bez payloadu w logach".
        logger.exception(
            "advisor_backend_error",
            extra={
                "request_id": request_id,
                "user_id": user_id,
                "reason": "advisor_unavailable",
            },
        )
        return _response(503, {"error": "advisor unavailable", "reason": "advisor_unavailable"})

    # Structured log dla CloudWatch metric filter (Step 7 cost guard).
    # `event=anthropic_call` dla pattern match w aws_cloudwatch_log_metric_filter.
    if usage is not None:
        logger.info(
            "anthropic_call",
            extra={
                "request_id": request_id,
                "user_id": user_id,
                "handler": "advisor_dinner",
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "cache_read_input_tokens": usage["cache_read_input_tokens"],
                "cache_creation_input_tokens": usage["cache_creation_input_tokens"],
                "cache_hit": False,
            },
        )
    else:
        logger.info(
            "advisor_cache_hit",
            extra={
                "request_id": request_id,
                "user_id": user_id,
                "handler": "advisor_dinner",
                "cache_hit": True,
            },
        )

    return _response(200, response.model_dump())
