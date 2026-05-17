"""GET /api/strava/oauth/start — initiates Strava OAuth flow.

Flow:
1. Verify JWT cookie (musi być zalogowany w bodysync żeby wiedzieć kto authorizes)
2. Mint cryptographic state, persist w DDB z user_id + 10min TTL
3. Read SSM /bodysync/strava/client_id
4. Build authorize URL, return 302

Frontend ("Połącz ze Stravą" button w tab Aktywności) wywołuje ten endpoint
przez `window.location` (browser following 302 do strava.com).
"""

from __future__ import annotations

from typing import Any

from handlers.strava_oauth_start.service import build_authorize_url, mint_state
from shared.auth import AuthError, verify_jwt
from shared.http import extract_session_cookie
from shared.logging import get_logger
from shared.ssm import get_param

logger = get_logger("strava_oauth_start")

CLIENT_ID_PARAM = "/bodysync/strava/client_id"


def _redirect(location: str) -> dict[str, Any]:
    return {
        "statusCode": 302,
        "headers": {"Location": location},
        "body": "",
    }


def _error(status: int, body: str) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "text/plain"},
        "body": body,
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "local")

    token = extract_session_cookie(event)
    if not token:
        logger.info("missing_session", extra={"request_id": request_id})
        return _error(401, "missing session cookie")

    try:
        payload = verify_jwt(token)
    except AuthError as e:
        logger.info(
            "invalid_session",
            extra={"request_id": request_id, "reason": str(e)},
        )
        return _error(401, "invalid session")

    user_id = payload.get("user_id")
    if not user_id:
        return _error(401, "user_id missing in jwt")

    client_id = get_param(CLIENT_ID_PARAM, decrypt=False)
    if not client_id or client_id == "PLACEHOLDER":
        # Owner nie wpisał jeszcze real client_id w SSM — fail loud.
        logger.error(
            "client_id_placeholder",
            extra={"request_id": request_id, "user_id": user_id},
        )
        return _error(503, "strava integration not configured (client_id missing)")

    state = mint_state(user_id)
    authorize_url = build_authorize_url(client_id, state)

    logger.info(
        "strava_oauth_start_initiated",
        extra={
            "request_id": request_id,
            "user_id": user_id,
            "handler": "strava_oauth_start",
        },
    )
    return _redirect(authorize_url)
