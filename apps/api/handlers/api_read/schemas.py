"""Response schemas dla GET endpoints frontu (Sprint 7 MVP)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class MeResponse(BaseModel):
    user_id: str
    email: str
    name: str | None = None


class BiometryDay(BaseModel):
    """Wszystkie metryki dla jednego dnia, zagregowane per metric type.

    HRV ma listę punktów (multi-point z timestampem), reszta ma single value.
    Frontend renderuje tabelę po metrykach × dni.
    """

    date: str  # ISO YYYY-MM-DD
    metrics: dict[str, Any]  # metric_name → value (number lub list dla HRV)


class BiometryResponse(BaseModel):
    days: list[BiometryDay]
