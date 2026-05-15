"""Pydantic schemas dla POST /api/measurements — manual body tape measurements.

Sprint 12 — pomiary obwodów (talia/biodra/klatka/biceps/udo) wpisywane raz
w tygodniu. Każda metryka opcjonalna (user może wpisać tylko zmienione
pola), ale model-level validator wymaga ≥1 non-None — bez tego POST jest
no-op'em.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, model_validator

# YYYY-MM-DD — same regex jak HAE webhook + advisor_chat conversation_date.
# Pełna walidacja kalendarzowa (np. 2026-02-30) niepotrzebna — frontend
# wysyła zawsze `localTodayIso()` w MVP, regex chroni przed SK injection.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# 5 obwodów ciała (cm). Range 0 < x < 500 chwyta typowe biometric: talia
# ~50-150 cm, biceps ~20-50 cm, udo ~40-80 cm. Walidacja na `Field`
# (gt/lt) — Pydantic odrzuca przed model_validator, więc -1 / 999 NIE
# leci do "at least one metric required" trapu.
_METRIC_FIELDS = ("waist_cm", "hips_cm", "chest_cm", "biceps_cm", "thigh_cm")


class MeasurementsRequest(BaseModel):
    """Body POST /api/measurements.

    Date format `YYYY-MM-DD` (regex-validated). Wszystkie 5 obwodów
    opcjonalne — model_validator pilnuje że ≥1 jest non-None (inaczej
    request nic by nie robił).
    """

    date: str = Field(description="YYYY-MM-DD format")
    waist_cm: float | None = Field(default=None, gt=0, lt=500)
    hips_cm: float | None = Field(default=None, gt=0, lt=500)
    chest_cm: float | None = Field(default=None, gt=0, lt=500)
    biceps_cm: float | None = Field(default=None, gt=0, lt=500)
    thigh_cm: float | None = Field(default=None, gt=0, lt=500)

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
