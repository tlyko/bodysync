"""Pydantic schemas dla POST /api/waitlist.

Public landing form — bez JWT auth. 3 walidacje poza email:
- `consent` MUSI być True (RODO checkbox required by landing UX + EU prawo).
- `honeypot` MUSI być pusty (anti-bot — hidden field, bot fills, user nie).
- `interest` cap 500 znaków (DDB attr size + abuse guard).

Field validators raise `ValueError` z fixed strings; handler.py mapuje
honeypot path na 200 silent (bot signal — NIE 422, żeby nie nauczyć bota
co poszło źle), resztę na 422 z sanitized error fields.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator


class WaitlistSignupRequest(BaseModel):
    """Body POST /api/waitlist — public landing form.

    Order field-validators ma znaczenie: Pydantic v2 sprawdza pola w
    deklaracji order, więc honeypot przed consent. Praktycznie bez efektu
    bo bot zwykle wypełnia oba, ale konwencja: ważniejszy guard (silent
    200) wcześniej.
    """

    email: EmailStr
    consent: bool
    honeypot: str = ""
    interest: str | None = Field(default=None, max_length=500)

    @field_validator("consent", mode="after")
    @classmethod
    def _consent_must_be_true(cls, v: bool) -> bool:
        """RODO consent musi być explicite True (checkbox checked)."""
        if v is not True:
            raise ValueError("consent_required")
        return v

    @field_validator("honeypot", mode="after")
    @classmethod
    def _honeypot_must_be_empty(cls, v: str) -> str:
        """Bot signal — fill honeypot = `ValueError("honeypot_filled")`.

        Handler rozpoznaje błąd po `msg == "honeypot_filled"` w
        `ValidationError.errors()` i zwraca 200 silently (NIE 422).
        """
        if v:
            raise ValueError("honeypot_filled")
        return v
