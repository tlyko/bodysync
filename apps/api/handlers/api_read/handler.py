"""AWS Lambda dispatcher dla GET endpointów frontu.

Routes:
  GET /api/me            — bieżący user (z PROFILE w DDB)
  GET /api/biometry      — Apple Health metrics ostatnich 7 dni (default)

Auth: JWT cookie `bodysync_session` (set przez google_auth Lambda).
Cookie wysyłane przez przeglądarkę dzięki Domain=.bodysync.pl + SameSite=Lax.
HTTP API v2 daje cookies w `event["cookies"]` jako lista stringów
"name=value" (nie sparsowane, filterujemy po prefiksie).
"""

from __future__ import annotations

from typing import Any

from handlers.api_read.schemas import BiometryResponse
from handlers.api_read.service import ProfileNotFoundError, get_biometry, get_me
from shared.auth import AuthError, verify_jwt
from shared.http import extract_session_cookie, response
from shared.logging import get_logger

logger = get_logger("api_read")

DEFAULT_BIOMETRY_DAYS = 7
MAX_BIOMETRY_DAYS = 90


def _parse_days(event: dict[str, Any]) -> int:
    raw = (event.get("queryStringParameters") or {}).get("days")
    if not raw:
        return DEFAULT_BIOMETRY_DAYS
    try:
        days = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_BIOMETRY_DAYS
    return max(1, min(MAX_BIOMETRY_DAYS, days))


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "local")

    token = extract_session_cookie(event)
    if not token:
        logger.info("missing_session", extra={"request_id": request_id})
        return response(401, {"error": "missing session cookie"})

    try:
        payload = verify_jwt(token)
    except AuthError:
        logger.info("invalid_session", extra={"request_id": request_id})
        return response(401, {"error": "invalid session"})

    user_id = payload.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        logger.warning("session_no_user_id", extra={"request_id": request_id})
        return response(401, {"error": "invalid session payload"})

    route = event.get("routeKey", "")

    if route == "GET /api/me":
        try:
            me = get_me(user_id)
        except ProfileNotFoundError:
            return response(404, {"error": "profile not found"})
        logger.info(
            "me_ok", extra={"request_id": request_id, "user_id": user_id, "handler": "api_read"}
        )
        return response(200, me.model_dump())

    if route == "GET /api/biometry":
        days = _parse_days(event)
        items = get_biometry(user_id, days=days)
        body = BiometryResponse(days=items).model_dump()
        logger.info(
            "biometry_ok",
            extra={
                "request_id": request_id,
                "user_id": user_id,
                "handler": "api_read",
                "days_returned": len(items),
            },
        )
        return response(200, body)

    logger.warning("unknown_route", extra={"request_id": request_id, "routeKey": route})
    return response(404, {"error": "not found"})
