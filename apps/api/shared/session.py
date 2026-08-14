"""Rozpoznanie zalogowanego użytkownika — jedno miejsce dla wszystkich handlerów.

Do Sprintu 12 każdy handler robił to sam: `extract_session_cookie` →
`verify_jwt` → wyciągnięcie `user_id`. Trzy powtórzone bloki w kilkunastu
plikach i — co ważniejsze — **żadnego miejsca, w którym dałoby się wpiąć
unieważnianie sesji**. JWT był bezstanowy i żył 30 dni, więc `POST /api/auth/logout`
kasował wyłącznie cookie w przeglądarce: skradziony token działał do `exp`
niezależnie od wylogowania.

`resolve_session` domyka trzy rzeczy naraz (audyt bezpieczeństwa 2026-08-14):

1. **`token_version`** — profil trzyma licznik, token niesie claim `tv`.
   Bump licznika unieważnia wszystkie wcześniej wydane sesje użytkownika.
   Brak claimu i brak atrybutu czyta się jako `0`, więc cookie sprzed deployu
   działa dalej — dopiero pierwszy bump je wywala, i o to chodzi.
2. **Istnienie profilu** — token po `DELETE /api/me/account` przestaje działać
   od razu, zamiast dostawać 200 z pustymi danymi (a po ponownym użyciu tego
   samego `user_id` — cudze dane).
3. **Jednolity 401** — wołający nie musi rozróżniać "brak cookie" od "zły
   podpis" od "unieważniona"; różnica idzie do logu, nie do odpowiedzi.

Koszt: jeden `GetItem` na profil per request (~2 ms, 0.5 RCU). Przy dwóch
użytkownikach to cena, której nie widać ani w rachunku, ani w latencji.
"""

from __future__ import annotations

from typing import Any

from shared.auth import AuthError, verify_jwt
from shared.dynamo import get_item, increment_attr
from shared.http import extract_session_cookie

TOKEN_VERSION_ATTR = "token_version"


class SessionError(Exception):
    """Sesja nieważna z dowolnego powodu — handler zamienia to na 401.

    `reason` to stały, krótki kod do structured logu (nie trafia do
    odpowiedzi HTTP — nie podpowiadamy atakującemu, na czym poległ).
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _profile(user_id: str) -> dict[str, Any]:
    profile = get_item(f"USER#{user_id}", "PROFILE")
    if profile is None:
        raise SessionError("profile_missing")
    return profile


def current_token_version(user_id: str) -> int:
    """Aktualny licznik unieważnień. Profil bez atrybutu = `0`."""
    raw = _profile(user_id).get(TOKEN_VERSION_ATTR, 0)
    try:
        return int(raw)
    except (TypeError, ValueError):
        # Zepsuty atrybut nie może otworzyć furtki — traktujemy jak 0, czyli
        # zgodnie z tokenami legacy, ale bump i tak go nadpisze liczbą.
        return 0


def bump_token_version(user_id: str) -> int:
    """Unieważnia wszystkie sesje użytkownika. Zwraca nową wartość licznika."""
    return increment_attr(f"USER#{user_id}", "PROFILE", TOKEN_VERSION_ATTR)


def resolve_session(event: dict[str, Any]) -> str:
    """Zwraca `user_id` właściciela ważnej sesji albo rzuca `SessionError`.

    Wynik jest jedynym źródłem `user_id` dla zapytań do DDB — nigdy nie bierz
    go z body ani z query stringa (CLAUDE.md, reguła PK isolation).
    """
    token = extract_session_cookie(event)
    if not token:
        raise SessionError("cookie_missing")

    try:
        payload = verify_jwt(token)
    except AuthError as exc:
        raise SessionError("jwt_invalid") from exc

    user_id = payload.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        raise SessionError("jwt_without_user_id")

    claimed = payload.get("tv", 0)
    if not isinstance(claimed, int) or isinstance(claimed, bool):
        # `tv` z JSON-a jest liczbą albo nie ma go wcale; string czy obiekt
        # oznacza token spoza naszego mintera.
        raise SessionError("jwt_bad_token_version")

    if claimed != current_token_version(user_id):
        raise SessionError("session_revoked")

    return user_id
