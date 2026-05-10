"""Pydantic schemas dla POST /api/profile/suggest-activity-level (Sprint 10 A0.5).

LLM ocenia poziom aktywności dziennej w skali Mifflin-St Jeor (5 poziomów)
na podstawie last 7d danych Strava + biometry. Schema enforce'uje literal —
LLM nie może wymyślić innego stringu (Pydantic ValidationError → handler 502).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ActivitySuggestionRequest(BaseModel):
    """Body POST /api/profile/suggest-activity-level — pusty na MVP.

    Future extension: opcjonalny `lookback_days` override (default 7).
    """

    pass


class ActivitySuggestion(BaseModel):
    """LLM output — JSON enforced przez prompt + Pydantic validate."""

    level: Literal["sedentary", "light", "moderate", "heavy", "athlete"]
    reasoning: str = Field(
        min_length=1,
        max_length=500,
        description="Polski tekst 1-3 zdania, konkretnie co user robi",
    )


class ActivitySuggestionResponse(BaseModel):
    """Handler response — wraps LLM output z meta (data window użyty)."""

    level: Literal["sedentary", "light", "moderate", "heavy", "athlete"]
    reasoning: str
    activities_count: int = Field(description="Liczba Strava activities w 7d window")
    avg_steps: int | None = Field(default=None, description="Średnio kroków/dzień")
    avg_kcal_active: int | None = Field(default=None, description="Średnio kcal aktywnych/dzień")
