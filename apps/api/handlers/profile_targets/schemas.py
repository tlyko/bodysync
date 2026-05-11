"""Pydantic schemas dla GET/PUT /api/profile/targets + POST /api/profile/calculate-tdee."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# Activity multiplier mapping (Mifflin-St Jeor + Harris-Benedict consensus).
# Reprezentuje przeciętne dzienne movement / NEAT poza struktryzowanymi
# treningami (treningi są dorzucone osobno przez kcal_active w Strava/HAE).
ACTIVITY_LEVELS = {
    "sedentary": 1.2,  # praca biurowa, brak ćwiczeń
    "light": 1.375,  # 1-3 dni/tydzień lekkie ćwiczenia
    "moderate": 1.55,  # 3-5 dni/tydzień umiarkowane
    "heavy": 1.725,  # 6-7 dni/tydzień intensywne
    "athlete": 1.9,  # 2× dziennie / fizyczna praca
}

# Goal kcal modifier — typowe wartości dla healthy rate of change.
# -500 kcal/day = ~-0.5 kg/tydzień (3500 kcal/lb fat).
# +300 kcal/day = ~+0.3 kg/tydzień (lean bulk, minimal fat gain).
GOAL_MODIFIERS = {
    "loss": -500,
    "maintain": 0,
    "gain": 300,
}


class BodyProfile(BaseModel):
    """Stable user attributes do BMR/TDEE calculation.

    Persistent w PROFILE row — owner wpisuje raz w wizardzie, potem zapomina.
    Wszystkie 5 pól wymagane do kalkulacji. Future: advisor może injektować
    `<body_profile>` block dla precyzyjnego coachingu.
    """

    height_cm: int = Field(ge=140, le=220, description="Wzrost w cm")
    age: int = Field(ge=18, le=100, description="Wiek w latach")
    sex: Literal["male", "female"] = Field(description="Płeć biologiczna (BMR formula)")
    activity_level: Literal["sedentary", "light", "moderate", "heavy", "athlete"] = Field(
        description="Poziom aktywności poza strukturyzowanymi treningami"
    )
    goal: Literal["loss", "maintain", "gain"] = Field(description="Cel sylwetkowy")


class TargetsPayload(BaseModel):
    """Body PUT /api/profile/targets — 4 makro pola required, body_profile opcjonalny.

    Body profile gdy obecny → jednoczesny update (frontend wizard po
    akceptacji proposal robi single PUT z body_profile + 4 makro).
    """

    kcal_target: int = Field(ge=1000, le=5000)
    protein_target_g: int = Field(ge=30, le=300)
    fat_target_g: int = Field(ge=20, le=200)
    carbs_target_g: int = Field(ge=30, le=500)
    body_profile: BodyProfile | None = None


class TargetsResponse(BaseModel):
    """Response GET /api/profile/targets — pełne 4 pola makro + opcjonalny body_profile.

    `is_default` flag pozwala UI pokazać "to jest fallback, ustaw swoje" CTA.
    `body_profile` None gdy owner jeszcze nie przeszedł przez wizard TDEE.

    Sprint 11 PR4 — read-only TDEE state (init przy body_profile save,
    update przez `tdee_recalc` Lambda). Frontend wyświetla badge
    `tdee_adaptive` vs `tdee_baseline` w Settings tab (PR5).
    """

    kcal_target: int
    protein_target_g: int
    fat_target_g: int
    carbs_target_g: int
    is_default: bool
    body_profile: BodyProfile | None = None
    tdee_baseline: int | None = None
    tdee_adaptive: int | None = None
    tdee_last_recalc: dict[str, Any] | None = None
    tdee_history: list[dict[str, Any]] = Field(default_factory=list)


class CalculateTDEERequest(BaseModel):
    """Body POST /api/profile/calculate-tdee.

    `body_profile` może być pominięty — wtedy backend czyta z PROFILE row.
    Gdy nadany — używa dostarczone wartości (preview przed save).
    `weight_kg` override gdy nadany; default: latest z DDB BIOMETRY (last 7d).
    """

    body_profile: BodyProfile | None = None
    weight_kg: float | None = Field(default=None, ge=30.0, le=250.0)


class CalculateTDEEResponse(BaseModel):
    """Output kalkulacji — proposed values, NIE persisted.

    Frontend pokazuje preview, user akceptuje → osobny PUT /api/profile/targets
    z proposed values + body_profile.
    """

    bmr: int = Field(description="Basal Metabolic Rate (Mifflin-St Jeor)")
    tdee_maintenance: int = Field(description="BMR × activity multiplier")
    target_kcal: int = Field(description="TDEE + goal modifier (deficit/surplus)")
    target_protein_g: int = Field(description="1.8 g/kg lean body mass approx")
    target_fat_g: int = Field(description="0.9 g/kg, ~25-30% kcal")
    target_carbs_g: int = Field(description="Reszta kcal po protein + fat (4 kcal/g)")
    weight_kg_used: float = Field(description="Waga użyta w kalkulacji (provided lub z BIOMETRY)")
