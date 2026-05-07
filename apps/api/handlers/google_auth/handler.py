"""AWS Lambda entrypoint dla POST /api/auth/google.

API Gateway HTTP API v2 event format. Zwraca:
- 200 + body LoginResponse + Set-Cookie session=JWT (HttpOnly Secure SameSite=Lax 30d)
- 400 invalid body
- 401 invalid Google token
- 403 email spoza allowlisty
- 500 unexpected
"""

from __future__ import annotations

import json
import os
from typing import Any

from pydantic import ValidationError

from handlers.google_auth.schemas import LoginRequest
from handlers.google_auth.service import (
    EmailNotAllowedError,
    GoogleTokenError,
    login,
)
from shared.logging import get_logger

logger = get_logger("google_auth")

COOKIE_NAME = "bodysync_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def _response(status: int, body: dict[str, Any], cookie: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
    if cookie is not None:
        out["cookies"] = [cookie]
    return out


def _build_cookie(token: str) -> str:
    """Build Set-Cookie header value.

    W prod cookie ma `Domain=.bodysync.pl` żeby był współdzielony między
    `bodysync.pl` (frontend) a `api.bodysync.pl` (backend) — JWT session
    z POST /api/auth/google trafia do same-parent cookie store i jest
    wysyłany przez fetch z frontu.

    W local (np. wsparcie dla Vite proxy do localhost API) — Domain
    pominięte (cookie per-host).
    """
    is_prod = os.environ.get("ENV", "prod") != "local"
    parts = [
        f"{COOKIE_NAME}={token}",
        "Path=/",
        f"Max-Age={COOKIE_MAX_AGE}",
        "HttpOnly",
        "SameSite=Lax",
    ]
    if is_prod:
        parts.append("Secure")
        parts.append("Domain=.bodysync.pl")
    return "; ".join(parts)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "local")
    raw_body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64

        raw_body = base64.b64decode(raw_body).decode("utf-8")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning("invalid json", extra={"request_id": request_id})
        return _response(400, {"error": "invalid json body"})

    try:
        req = LoginRequest.model_validate(payload)
    except ValidationError as e:
        # `e.errors()` zawiera `input` field z surowym user-supplied value —
        # wycieka payload attackera do response (XSS reflection vector dla
        # frontu który wyświetlałby `details`). Sanityzujemy do `loc + type`
        # — frontend i tak wie czego brakuje (LoginRequest ma jedno pole).
        sanitized = [{"loc": err["loc"], "type": err["type"]} for err in e.errors()]
        logger.warning(
            "invalid payload", extra={"request_id": request_id, "handler": "google_auth"}
        )
        return _response(400, {"error": "invalid payload", "details": sanitized})

    try:
        body, token = login(req)
    except GoogleTokenError as e:
        logger.info(
            "google token rejected",
            extra={"request_id": request_id, "handler": "google_auth", "reason": str(e)},
        )
        return _response(401, {"error": "invalid google token"})
    except EmailNotAllowedError:
        logger.info(
            "email not allowed",
            extra={"request_id": request_id, "handler": "google_auth"},
        )
        return _response(403, {"error": "email not allowed"})
    except Exception:
        logger.exception("login failed", extra={"request_id": request_id})
        return _response(500, {"error": "internal"})

    logger.info(
        "login ok",
        extra={
            "request_id": request_id,
            "user_id": body.user_id,
            "handler": "google_auth",
        },
    )
    return _response(200, body.model_dump(), cookie=_build_cookie(token))
