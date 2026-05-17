"""Pydantic schemas dla DELETE /api/me/account — RODO Art. 17 erasure.

Confirmation phrase wymagana — `{"confirm": "DELETE"}`. JWT+CSRF i tak chronią
przed cross-site, ale wpisanie literałów w body redukuje accidental call
(misclick w UI, broken fetch retry, automation bug).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class DeleteAccountRequest(BaseModel):
    """Body DELETE /api/me/account."""

    confirm: Literal["DELETE"]
