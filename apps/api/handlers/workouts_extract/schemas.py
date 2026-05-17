"""Pydantic schemas dla POST /api/workouts/extract.

Frontend wysyła `trainings: Training[]` (output `apps/web/src/components/dashboard/planParser.ts`)
+ `today_iso` (data lokalna w boundary Warsaw). Backend per-exercise woła
Haiku → structured sets → DDB.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, model_validator

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Frontend `planParser.ts` shape — mirror dokładnie (bez TS-specific types).


class ExerciseIn(BaseModel):
    """Pojedyncze ćwiczenie z `Section.exercises[]` parsera frontu."""

    number: str = Field(min_length=1, max_length=8)
    cells: list[str] = Field(min_length=1, max_length=20)


class SectionIn(BaseModel):
    """Sekcja (Rozgrzewka lub Trening A/B/C) — `Training.sections[]`."""

    label: str | None = Field(default=None, max_length=100)
    headers: list[str] = Field(min_length=1, max_length=20)
    exercises: list[ExerciseIn] = Field(default_factory=list, max_length=50)


class TrainingIn(BaseModel):
    """Jeden Training (Trening A / B / C) z jednego tygodnia.

    Alias `weekIdx`/`weekTotal` mirror frontend planParser.ts TypeScript shape
    (camelCase). Snake_case w Pythonie, JSON pole z camelCase przez alias.
    """

    model_config = {"populate_by_name": True}

    name: str = Field(min_length=1, max_length=100)
    week_idx: int = Field(ge=1, le=52, alias="weekIdx")
    week_total: int = Field(ge=1, le=52, alias="weekTotal")
    sections: list[SectionIn] = Field(min_length=1, max_length=10)


class ExtractRequest(BaseModel):
    """Body POST /api/workouts/extract."""

    today_iso: str = Field(description="YYYY-MM-DD, owner local date")
    trainings: list[TrainingIn] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def _date_format(self) -> ExtractRequest:
        if not _DATE_RE.match(self.today_iso):
            raise ValueError("invalid_date_format")
        return self


# ─── Output schema ──────────────────────────────────────────────────────


class WorkoutSet(BaseModel):
    """Pojedynczy set (waga + reps). `weight_kind`:
    - "kg" — `weight_kg` zawiera wartość
    - "bw" — bodyweight, `weight_kg` typowo null
    - "other" — fallback gdy LLM nie wie (np. "lekka", "do ostatka")
    """

    weight_kg: float | None = Field(default=None, ge=0, le=1000)
    weight_kind: str = Field(default="kg", pattern="^(kg|bw|other)$")
    reps: int = Field(ge=0, le=100)


class ExtractedExercise(BaseModel):
    """Per-exercise output dla 1 entry w DDB."""

    date: str  # YYYY-MM-DD
    training_name: str
    exercise_number: str
    exercise_name: str
    sets: list[WorkoutSet] = Field(default_factory=list)
    rir: int | None = Field(default=None, ge=0, le=10)
    notes: str | None = Field(default=None, max_length=500)


class ExtractResponse(BaseModel):
    """200 response z counts + per-exercise outcomes (debug)."""

    extracted: int
    skipped: int
    errors: int
    items: list[ExtractedExercise] = Field(default_factory=list)
