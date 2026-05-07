"""Pydantic schemas dla POST /api/auth/google."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Body z frontendu po pomyślnym Google Sign-In."""

    id_token: str = Field(min_length=10, description="Google ID token JWT")


class LoginResponse(BaseModel):
    """Body zwracany do frontu (cookie idzie w Set-Cookie header)."""

    user_id: str
    email: str
    name: str | None = None
