"""CSRF protection via double-submit cookie pattern.

Sec audit 2026-05-16 P1-4. Sprint #2 owner zdecydował zostać przy
`SameSite=Lax` (Strict zepsuje Strava OAuth callback flow — cross-site
redirect z `https://www.strava.com` nie wysyła Strict cookie). Zamiast tego
chronimy state-changing endpoints przez CSRF token.

Pattern:
1. Frontend generuje token `crypto.randomUUID()`, zapisuje w cookie
   `bodysync_csrf` (NIE HttpOnly — JS musi czytać) i wysyła w request header
   `X-CSRF-Token` dla każdego non-safe method (POST/PUT/DELETE/PATCH).
2. Backend porównuje cookie value z header value (constant-time). Mismatch
   lub brak → 403.

Cross-site malicious page nie może:
- odczytać cookie `bodysync_csrf` z `bodysync.pl` (Same-Origin Policy)
- ustawić własnego `X-CSRF-Token` header w `fetch` cross-origin (CORS
  preflight wymaga że origin jest whitelisted)

Czyli atakujący nie wie co wstawić w X-CSRF-Token → backend odrzuca.
"""

from __future__ import annotations

import hmac
from typing import Any

CSRF_COOKIE_NAME = "bodysync_csrf"
CSRF_HEADER_NAME = "x-csrf-token"  # HTTP API v2 lower-cases header names


class CSRFError(Exception):
    """CSRF token missing or mismatched."""


def _extract_cookie(event: dict[str, Any]) -> str | None:
    cookies: list[str] = event.get("cookies") or []
    for cookie in cookies:
        if cookie.startswith(f"{CSRF_COOKIE_NAME}="):
            return cookie.split("=", 1)[1]
    headers: dict[str, str] = event.get("headers") or {}
    raw: str | None = headers.get("cookie") or headers.get("Cookie")
    if raw:
        for part in raw.split(";"):
            stripped = part.strip()
            if stripped.startswith(f"{CSRF_COOKIE_NAME}="):
                return stripped.split("=", 1)[1]
    return None


def _extract_header(event: dict[str, Any]) -> str | None:
    headers: dict[str, str] = event.get("headers") or {}
    # HTTP API v2 lower-cases header names; defensive `or` dla legacy paths.
    return (
        headers.get(CSRF_HEADER_NAME) or headers.get("X-CSRF-Token") or headers.get("X-Csrf-Token")
    )


def verify_csrf(event: dict[str, Any]) -> None:
    """Raise CSRFError if request lacks valid CSRF token.

    Should be called after JWT verification but before any state mutation.
    Compares cookie value and header value in constant time.
    """
    cookie_token = _extract_cookie(event)
    header_token = _extract_header(event)
    if not cookie_token or not header_token:
        raise CSRFError("csrf token missing")
    if not hmac.compare_digest(cookie_token, header_token):
        raise CSRFError("csrf token mismatch")
