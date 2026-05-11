"""Pydantic schemas dla adaptive TDEE recalc — pure service IO + persistowany audit.

`BiometryWindow` to input do `service.recalculate_tdee()` (handler buduje go z
DDB Query w PR2). `RecalcResult` to output pure function — handler decyduje
co z nim zrobić (persist / return jako HTTP body). `RecalcHistoryEntry`
opisuje single entry w `tdee_history` list (cap 20 FIFO w PR2).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict


class BiometryWindow(BaseModel):
    """Input do `recalculate_tdee` — surowe punkty z BIOMETRY w window 14d.

    Lists mogą być niesortowane (handler dostarcza w kolejności DDB Query).
    Pure function sortuje gdzie to potrzebne (anchor matching, winsorize).
    """

    model_config = ConfigDict(extra="forbid")

    weights: list[tuple[date, float]]
    kcals: list[tuple[date, int]]


class RecalcResult(BaseModel):
    """Output `recalculate_tdee` — wystarczy do persist + return jako HTTP body.

    `ok=True` także dla `skipped=True` (skip nie jest błędem — to expected
    przy onboardingu / brakach danych). Handler zwraca 200 z `skipped=true`
    zamiast 400 (per ADR-008 sec 3).
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    skipped: bool
    reason: (
        Literal[
            "insufficient_kcal_data",
            "insufficient_weight_data",
            "weight_anchor_missing",
            "weight_now_missing",
            "kcal_in_avg_unrealistic",
            "baseline_not_initialized",
        ]
        | None
    )
    tdee_before: int
    tdee_after: int
    kcal_in_avg: int | None
    waga_delta_kg: float | None
    adjustment: int | None
    capped: bool


class RecalcHistoryEntry(BaseModel):
    """Single entry w `tdee_history` list (PROFILE row).

    `event="initial"` — pierwsze save body_profile (Step 4).
    `event="recalc"` — udana iteracja korekty (PR2).
    `event="skipped"` — brak danych / safety guard zatrzymał kalkulację.
    `event="body_profile_change"` — reset baseline po zmianie wzrost/wiek/aktywność/cel.
    """

    model_config = ConfigDict(extra="forbid")

    date: date
    event: Literal["recalc", "body_profile_change", "skipped", "initial"]
    before: int | None
    after: int | None
    kcal_in_avg: int | None
    waga_delta_kg: float | None
    adjustment: int | None
    capped: bool
    reason: str | None
