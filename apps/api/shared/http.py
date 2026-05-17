"""Shared HTTP helpers dla Lambda handlerów (API GW HTTP API v2).

Eliminuje ~300 LOC duplikacji `_extract_session_cookie` + `_response`
powtarzanych w 9+ handlerach (dług techniczny P1 z docs/audit-2026-05-16.md).

`extract_session_cookie` — czyta `bodysync_session` JWT z eventu (cookies array
najpierw, fallback na raw `Cookie` header). Per audit C1 — fallback istnieje
bo HTTP API v2 czasem nie populuje `cookies` array dla manual fetch'ów
(np. curl bez `--cookie-jar`).

`response` — buduje envelope statusCode + JSON body z `default=str`
serializer (DDB Decimal → string fallback).
"""

from __future__ import annotations

import json
from typing import Any

COOKIE_NAME = "bodysync_session"


def extract_session_cookie(event: dict[str, Any]) -> str | None:
    """Wyciąga JWT z bodysync_session cookie lub None gdy brak."""
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


def response(status: int, body: dict[str, Any] | list[Any]) -> dict[str, Any]:
    """API GW HTTP API v2 response envelope (JSON body, default str serializer)."""
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }
