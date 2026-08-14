"""Uwierzytelnienie requestów MCP — Bearer token z flow OAuth 2.0.

**Ten moduł jest celowo niekompletny do PR 4.** Serwer autoryzacji (dokumenty
`.well-known`, `/register`, `/authorize`, `/token`, PKCE S256) jest osobnym
krokiem — patrz ADR-010, decyzja 3. Do tego czasu `resolve_user_id` odrzuca
KAŻDY request, więc handler nie może zwrócić danych bez autoryzacji nawet
przez pomyłkę.

To nie jest tymczasowa dziura: handler nie jest podpięty do API Gateway
(Terraform dochodzi w PR 5), więc nic nie jest publicznie wystawione.
Kształt odpowiedzi 401 + `WWW-Authenticate` jest już zgodny ze spec, bo to
on uruchamia discovery po stronie klienta — PR 4 dokłada wyłącznie walidację
tokenu.
"""

from __future__ import annotations

from typing import Any


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
    """Zwraca `user_id` właściciela tokenu albo rzuca `AuthError`.

    PR 4 podmieni ciało na walidację tokenu wystawionego przez nasz serwer
    autoryzacji (podpis, exp, mapowanie token → user_id w DDB).
    """
    token = bearer_token(event)
    if token is None:
        raise AuthError("brak nagłówka Authorization: Bearer")
    raise AuthError("weryfikacja tokenu nie jest jeszcze zaimplementowana")
