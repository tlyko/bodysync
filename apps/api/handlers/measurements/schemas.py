"""Pydantic schemas dla POST /api/measurements — manual body + nutrition entry.

Sprint 12 — pomiary obwodów (talia/biodra/klatka/biceps/udo) wpisywane raz
w tygodniu. Sprint post-Recovery (2026-05-17) — rozszerzone o nutrition
fallback (kcal_in + P/F/C) gdy HAE offline. Każda metryka opcjonalna
(user może wpisać tylko zmienione pola), ale model-level validator wymaga
≥1 non-None — bez tego POST jest no-op'em.

Manual entry nadpisuje HAE dla danego date+metric (api_read service Pass 2
filtruje na source=="manual" → manual buckets wygrywają).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, model_validator

# YYYY-MM-DD — same regex jak HAE webhook + advisor_chat conversation_date.
# Pełna walidacja kalendarzowa (np. 2026-02-30) niepotrzebna — frontend
# wysyła zawsze `localTodayIso()` w MVP, regex chroni przed SK injection.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Wszystkie pola które handler iteruje. Mix:
# - obwody (cm), range 0 < x < 500: typowe biometric (talia ~50-150, biceps ~20-50)
# - kcal_in (kcal), range 0 < x ≤ 10000: typowo 1500-3500, górny limit łapie
#   typo (np. 25000 zamiast 2500)
# - makro (g), range 0 < x ≤ 1000: typowo P 100-200g, F 60-120g, C 200-400g
_METRIC_FIELDS = (
    "waist_cm",
    "hips_cm",
    "chest_cm",
    "biceps_cm",
    "thigh_cm",
    "kcal_in",
    "protein_g",
    "fat_g",
    "carbs_g",
)


class MeasurementsRequest(BaseModel):
    """Body POST /api/measurements.

    Date format `YYYY-MM-DD` (regex-validated). Obwody (cm) + nutrition
    (kcal_in/P/F/C) opcjonalne — model_validator pilnuje że ≥1 jest non-None.
    Nutrition manual override'uje HAE dla danego dnia (read-side precedence
    w api_read service).
    """

    date: str = Field(description="YYYY-MM-DD format")
    # Body measurements (cm).
    waist_cm: float | None = Field(default=None, gt=0, lt=500)
    hips_cm: float | None = Field(default=None, gt=0, lt=500)
    chest_cm: float | None = Field(default=None, gt=0, lt=500)
    biceps_cm: float | None = Field(default=None, gt=0, lt=500)
    thigh_cm: float | None = Field(default=None, gt=0, lt=500)
    # Nutrition (kcal_in + makro). 0 < x → wpisanie 0 niech będzie no-op
    # (pomijać pole, nie wysyłać). Górne limity chronią przed typos.
    kcal_in: float | None = Field(default=None, gt=0, le=10000)
    protein_g: float | None = Field(default=None, gt=0, le=1000)
    fat_g: float | None = Field(default=None, gt=0, le=1000)
    carbs_g: float | None = Field(default=None, gt=0, le=1000)

    @model_validator(mode="after")
    def _date_format(self) -> MeasurementsRequest:
        if not _DATE_RE.match(self.date):
            raise ValueError("invalid_date_format")
        return self

    @model_validator(mode="after")
    def _at_least_one_metric(self) -> MeasurementsRequest:
        if not any(getattr(self, f) is not None for f in _METRIC_FIELDS):
            raise ValueError("at_least_one_metric_required")
        return self
