"""JWT mint + verify. Secret z SSM (cache w shared/ssm.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from shared.ssm import SecretMisconfiguredError, load_secure_secret

JWT_SSM_PARAM = "/bodysync/jwt/signing_secret"
JWT_ALGORITHM = "HS256"
JWT_TTL_DAYS = 30
# HS256 wymaga ≥256 bitów entropii; 32 bytes minimum dla bezpiecznego HMAC.
JWT_SECRET_MIN_LENGTH = 32


class AuthError(Exception):
    """Raised when a token is missing, malformed, expired, or signed wrong."""


# Backward-compat alias — istniejące testy importują JwtSecretMisconfiguredError.
JwtSecretMisconfiguredError = SecretMisconfiguredError


def mint_jwt(user_id: str, *, ttl_days: int = JWT_TTL_DAYS, token_version: int = 0) -> str:
    """Sign a JWT carrying user_id + exp + token_version.

    `tv` to licznik unieważnień trzymany w `USER#{id}/PROFILE`. Sam token
    pozostaje bezstanowy — dopiero `shared.session.resolve_session` porównuje
    claim z aktualną wartością w profilu i odrzuca sesje sprzed bumpa.
    Domyślne `0` = "profil bez licznika", czyli stan przed Sprintem 12.
    """
    secret = load_secure_secret(JWT_SSM_PARAM, min_length=JWT_SECRET_MIN_LENGTH)
    now = datetime.now(UTC)
    payload = {
        "user_id": user_id,
        "tv": token_version,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=ttl_days)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def verify_jwt(token: str) -> dict[str, Any]:
    """Decode + verify signature + verify exp. Returns payload, raises AuthError."""
    secret = load_secure_secret(JWT_SSM_PARAM, min_length=JWT_SECRET_MIN_LENGTH)
    try:
        return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError as e:
        raise AuthError(f"invalid jwt: {e}") from e
