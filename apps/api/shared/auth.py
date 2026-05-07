"""JWT mint + verify. Secret z SSM (cache w shared/ssm.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from shared.ssm import get_param

JWT_SSM_PARAM = "/bodysync/jwt/signing_secret"
JWT_ALGORITHM = "HS256"
JWT_TTL_DAYS = 30
# HS256 wymaga ≥256 bitów entropii; 32 bytes minimum dla bezpiecznego HMAC.
# Terraform tworzy SSM param z value="PLACEHOLDER" — fail-fast jeśli owner
# nie wpisał prawdziwego sekretu (sec audit H2 — w przeciwnym razie każdy
# minted JWT podpisaną stringiem "PLACEHOLDER" dawałby fałszywą autentykację).
JWT_SECRET_MIN_LENGTH = 32


class AuthError(Exception):
    """Raised when a token is missing, malformed, expired, or signed wrong."""


class JwtSecretMisconfiguredError(RuntimeError):
    """JWT signing secret w SSM nie został ustawiony (PLACEHOLDER) lub zbyt krótki."""


def _load_secret() -> str:
    secret = get_param(JWT_SSM_PARAM)
    if secret == "PLACEHOLDER" or len(secret) < JWT_SECRET_MIN_LENGTH:
        raise JwtSecretMisconfiguredError(
            f"JWT signing secret in {JWT_SSM_PARAM} not configured "
            f"(must be ≥{JWT_SECRET_MIN_LENGTH} chars, not 'PLACEHOLDER')"
        )
    return secret


def mint_jwt(user_id: str, *, ttl_days: int = JWT_TTL_DAYS) -> str:
    """Sign a JWT carrying user_id + exp."""
    secret = _load_secret()
    now = datetime.now(UTC)
    payload = {
        "user_id": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=ttl_days)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def verify_jwt(token: str) -> dict[str, Any]:
    """Decode + verify signature + verify exp. Returns payload, raises AuthError."""
    secret = _load_secret()
    try:
        return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError as e:
        raise AuthError(f"invalid jwt: {e}") from e
