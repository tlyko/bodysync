"""Pydantic schemas dla diet check / progress narrative (Sprint 11.5 ADR-009).

Pivot ze Sprint 11 (deterministic adaptive TDEE recalc) → LLM-driven diet
review vs MANUAL `kcal_target`. Algorithm 14d window zostaje, output to
status classification + LLM narrative PL.

`BiometryWindow` reused z PR1 Sprint 11 — input shape pure function.
`DietCheckResult` REPLACES `RecalcResult`. `DietCheckHistoryEntry`
REPLACES `RecalcHistoryEntry` (cap 10 FIFO w PROFILE.diet_check_history).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

DietCheckStatus = Literal["on_track", "too_fast", "too_slow_or_gain"]

DietCheckSkipReason = Literal[
    "insufficient_kcal_data",
    "insufficient_weight_data",
    "weight_anchor_missing",
    "weight_now_missing",
    "no_kcal_target",
]


class BiometryWindow(BaseModel):
    """Input do `evaluate_diet_check` — surowe punkty z BIOMETRY w window 14d.

    Lists mogą być niesortowane (handler dostarcza w kolejności DDB Query).
    Pure function sortuje gdzie to potrzebne (anchor matching, winsorize).
    """

    model_config = ConfigDict(extra="forbid")

    weights: list[tuple[date, float]]
    kcals: list[tuple[date, int]]


class DietCheckResult(BaseModel):
    """Output `evaluate_diet_check` — deterministic compare + slot na LLM narrative.

    `skipped=True` to expected scenario (insufficient data / brak `kcal_target`
    manual save). Handler zwraca 200 z `skipped=true` zamiast 400.

    `narrative` wypełniany w handlerze przez LLM call (PR2). PR1 zwraca None
    + `narrative_unavailable=False` (LLM nie był wołany jeszcze).
    """

    model_config = ConfigDict(extra="forbid")

    skipped: bool
    skip_reason: DietCheckSkipReason | None

    # Input goal (manual lub z TDEE wizard) — co owner sobie ustawił.
    goal_kcal: int | None

    # Surowe agregaty 14d window — debug + UI secondary "Szczegóły" expansion.
    kcal_in_avg: int | None
    waga_now_kg: float | None
    waga_then_kg: float | None
    waga_delta_kg: float | None

    # Klasyfikacja deterministic — LLM dostaje to jako hint.
    expected_delta_kg: float | None
    actual_delta_kg: float | None
    diff_kg: float | None
    status: DietCheckStatus | None

    # LLM narrative (primary UI display) — PR2 wypełnia, PR1 zostaje None.
    narrative: str | None
    narrative_unavailable: bool


class DietCheckHistoryEntry(BaseModel):
    """Single entry w `diet_check_history` list (PROFILE row).

    Cap 10 FIFO — `cap_diet_check_history` w service. Mirror shape per
    `DietCheckResult` minus `narrative_unavailable` (storage compaction).
    """

    model_config = ConfigDict(extra="forbid")

    date: date
    skipped: bool
    skip_reason: DietCheckSkipReason | None
    goal_kcal: int | None
    kcal_in_avg: int | None
    waga_delta_kg: float | None
    diff_kg: float | None
    status: DietCheckStatus | None
    narrative: str | None
