"""AWS Lambda entrypoint dla POST /api/auth/logout.

Idempotentny — czyści cookie sesji niezależnie od tego czy JWT jest
ważny (lub czy w ogóle leci z requestem). UI wywołuje na "Wyloguj"
kliknięcie + frontend stan reset.

Set-Cookie z `Max-Age=0` (RFC 6265 §4.1.2.2) instruuje przeglądarkę
żeby usunęła cookie. Domain/Path muszą matchować original cookie
z google_auth handlera (`Domain=.bodysync.pl Path=/`) inaczej
przeglądarka nie znajdzie pasującego entry do usunięcia.
"""

from __future__ import annotations

import json
import os
from typing import Any

from shared.logging import get_logger

logger = get_logger("auth_logout")

COOKIE_NAME = "bodysync_session"


def _build_clear_cookie() -> str:
    """Build Set-Cookie header value, mirror google_auth z Max-Age=0."""
    is_prod = os.environ.get("ENV", "prod") != "local"
    parts = [
        f"{COOKIE_NAME}=",
        "Path=/",
        "Max-Age=0",
        "HttpOnly",
        "SameSite=Lax",
    ]
    if is_prod:
        parts.append("Secure")
        parts.append("Domain=.bodysync.pl")
    return "; ".join(parts)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "local")
    logger.info("logout", extra={"request_id": request_id, "handler": "auth_logout"})
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "cookies": [_build_clear_cookie()],
        "body": json.dumps({"ok": True}),
    }
