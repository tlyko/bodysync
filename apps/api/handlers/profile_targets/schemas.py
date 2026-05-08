"""Pydantic schemas dla GET/PUT /api/profile/targets."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TargetsPayload(BaseModel):
    """Body PUT /api/profile/targets — wszystkie 4 pola required.

    Ranges defensywne — owner sam wpisuje swoje wartości via UI form.
    """

    kcal_target: int = Field(ge=1000, le=5000)
    protein_target_g: int = Field(ge=30, le=300)
    fat_target_g: int = Field(ge=20, le=200)
    carbs_target_g: int = Field(ge=30, le=500)


class TargetsResponse(BaseModel):
    """Response GET /api/profile/targets — zawsze pełne 4 pola.

    Gdy DDB PROFILE row nie ma attrów → fallback defaults z `service.py`
    (te same co używa advisor_chat). `is_default` flag pozwala UI pokazać
    "to jest fallback, ustaw swoje" CTA.
    """

    kcal_target: int
    protein_target_g: int
    fat_target_g: int
    carbs_target_g: int
    is_default: bool
