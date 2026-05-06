"""JWT mint + verify. Secret z SSM (cache w shared/ssm.py)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from shared.ssm import get_param

JWT_SSM_PARAM = "/bodysync/jwt/signing_secret"
JWT_ALGORITHM = "HS256"
JWT_TTL_DAYS = 30


class AuthError(Exception):
    """Raised when a token is missing, malformed, expired, or signed wrong."""


def mint_jwt(user_id: str, *, ttl_days: int = JWT_TTL_DAYS) -> str:
    """Sign a JWT carrying user_id + exp."""
    secret = get_param(JWT_SSM_PARAM)
    now = datetime.now(UTC)
    payload = {
        "user_id": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=ttl_days)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def verify_jwt(token: str) -> dict[str, Any]:
    """Decode + verify signature + verify exp. Returns payload, raises AuthError."""
    secret = get_param(JWT_SSM_PARAM)
    try:
        return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])  # type: ignore[no-any-return]
    except jwt.InvalidTokenError as e:
        raise AuthError(f"invalid jwt: {e}") from e
