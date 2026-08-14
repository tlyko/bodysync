"""Uwierzytelnienie requestów MCP — Bearer token z flow OAuth 2.0.

Token wystawia nasz własny serwer autoryzacji (`handlers/mcp/oauth.py`).
Podpisany jest **osobnym** sekretem niż cookie sesyjne aplikacji, więc token
MCP nie może zostać użyty jako sesja `bodysync_session` — patrz komentarz
przy `oauth.TOKEN_SECRET_PARAM`.
"""

from __future__ import annotations

from typing import Any

from handlers.mcp.oauth import OAuthError, user_id_from_access_token


class AuthError(Exception):
    """Brak lub niepoprawny token — handler zamienia to na 401."""


def bearer_token(event: dict[str, Any]) -> str | None:
    """Wyciąga token z nagłówka `Authorization: Bearer <token>`.

    API Gateway HTTP v2 normalizuje nazwy nagłówków do lowercase.
    """
    headers = event.get("headers") or {}
    raw = headers.get("authorization") or headers.get("Authorization")
    if not isinstance(raw, str) or not raw:
        return None
    scheme, _, token = raw.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def resolve_user_id(event: dict[str, Any]) -> str:
    """Zwraca `user_id` właściciela tokenu albo rzuca `AuthError`."""
    token = bearer_token(event)
    if token is None:
        raise AuthError("brak nagłówka Authorization: Bearer")
    try:
        return user_id_from_access_token(token)
    except OAuthError as exc:
        raise AuthError(exc.description) from exc
