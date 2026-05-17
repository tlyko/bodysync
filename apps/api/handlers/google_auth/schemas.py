"""Pydantic schemas dla POST /api/auth/google."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Body z frontendu po pomyślnym Google Sign-In."""

    id_token: str = Field(min_length=10, description="Google ID token JWT")
    nonce: str = Field(
        min_length=16,
        max_length=128,
        description=(
            "Replay protection — frontend generuje crypto.randomUUID() przed "
            "google.accounts.id.initialize({nonce}), wysyła tu, backend "
            "weryfikuje że idinfo['nonce'] == req.nonce + single-use DDB."
        ),
    )


class LoginResponse(BaseModel):
    """Body zwracany do frontu (cookie idzie w Set-Cookie header)."""

    user_id: str
    email: str
    name: str | None = None
