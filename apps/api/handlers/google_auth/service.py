"""Logika google-auth osobno od Lambda event/context — testowalne bez mock'a Lambda runtime.

Flow:
1. Parse `LoginRequest` (Pydantic, raises ValidationError → 400)
2. Verify Google id_token (audience = OAuth client id z SSM)
3. Sprawdź email na allowliście (SSM JSON `[{"email", "user_id"}]`) → 403 jeśli brak
4. Upsert PROFILE w DDB (last_login)
5. Mint JWT z user_id, exp 30d
6. Return (LoginResponse, jwt_token) — handler składa Set-Cookie header
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from handlers.google_auth.schemas import LoginRequest, LoginResponse
from shared.auth import mint_jwt
from shared.dynamo import put_item
from shared.ssm import get_param

GOOGLE_CLIENT_ID_SSM = "/bodysync/google/oauth_client_id"
ALLOWED_EMAILS_SSM = "/bodysync/auth/allowed_emails"


class GoogleTokenError(Exception):
    """Google token nie przeszedł walidacji (zły issuer / audience / signature / exp)."""


class EmailNotAllowedError(Exception):
    """Email zweryfikowany przez Google, ale nie jest na 2-osobowej allowliście."""


def _verify_google_token(id_token_str: str) -> dict[str, Any]:
    client_id = get_param(GOOGLE_CLIENT_ID_SSM, decrypt=False)
    try:
        return google_id_token.verify_oauth2_token(  # type: ignore[no-untyped-call,no-any-return]
            id_token_str,
            google_requests.Request(),
            audience=client_id,
        )
    except (ValueError, Exception) as e:
        # google-auth raises ValueError for malformed tokens, GoogleAuthError for crypto.
        # Both → 401.
        raise GoogleTokenError(str(e)) from e


def _resolve_user_id(email: str) -> str:
    """Mapuje email → user_id po wcześniej wpisanej allowliście (JSON w SSM).

    Format SSM `/bodysync/auth/allowed_emails`:
        [{"email": "tlyko94@gmail.com", "user_id": "tomek"},
         {"email": "...", "user_id": "partner"}]
    """
    raw = get_param(ALLOWED_EMAILS_SSM, decrypt=False)
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as e:
        raise EmailNotAllowedError(f"allowlist not valid JSON: {e}") from e
    if not isinstance(entries, list):
        raise EmailNotAllowedError("allowlist must be a JSON array")
    for entry in entries:
        if isinstance(entry, dict) and entry.get("email") == email:
            user_id = entry.get("user_id")
            if isinstance(user_id, str) and user_id:
                return user_id
    raise EmailNotAllowedError(f"email not on allowlist: {email}")


def login(req: LoginRequest) -> tuple[LoginResponse, str]:
    """Zwraca (response_body, jwt_token). Handler dokleja Set-Cookie."""
    idinfo = _verify_google_token(req.id_token)
    email = idinfo.get("email")
    if not isinstance(email, str) or not idinfo.get("email_verified"):
        raise GoogleTokenError("token without verified email")

    user_id = _resolve_user_id(email)
    name = idinfo.get("name") if isinstance(idinfo.get("name"), str) else None

    put_item(
        pk=f"USER#{user_id}",
        sk="PROFILE",
        attrs={
            "email": email,
            "name": name,
            "last_login": datetime.now(UTC).isoformat(),
        },
    )

    token = mint_jwt(user_id)
    return LoginResponse(user_id=user_id, email=email, name=name), token
