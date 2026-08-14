"""Rejestr metryk BIOMETRY — mapowanie publicznej nazwy na wiersz w DDB.

Nazwy atrybutów zweryfikowane na produkcyjnych wierszach (2026-08-14), nie
zgadnięte: `weight.kg`, `bmi.value`, `body_fat.pct`, `resting_hr.bpm`,
`sleep.asleep`, obwody manualne `*.cm`, cumulative `kcal_*.kcal` / `*.g` /
`steps.count`.

Czego tu NIE ma i nie będzie bez integracji z Garmin Connect: `hrv`
i `body_battery`. Garmin nie wysyła ich do Apple Health (ADR-010, PR #177) —
scan tabeli potwierdził zero wierszy obu.
"""

from __future__ import annotations

from typing import NamedTuple


class Metric(NamedTuple):
    """Jak wyciągnąć skalarną wartość metryki z wiersza BIOMETRY.

    `sk_metric` — segment metryki w SK (`BIOMETRY#{date}#{sk_metric}`).
    `attr` — atrybut wiersza trzymający wartość.
    `unit` — jednostka do opisu w odpowiedzi (dla LLM, nie do przeliczeń).
    """

    sk_metric: str
    attr: str
    unit: str


# Skład ciała — `get_body_composition`.
BODY_METRICS: dict[str, Metric] = {
    "weight": Metric("weight", "kg", "kg"),
    "bmi": Metric("bmi", "value", "kg/m2"),
    "body_fat": Metric("body_fat", "pct", "%"),
    "lean_body_mass": Metric("lean_body_mass", "kg", "kg"),
    # Obwody wpisywane ręcznie przez POST /api/measurements.
    "waist": Metric("waist", "cm", "cm"),
    "hips": Metric("hips", "cm", "cm"),
    "chest": Metric("chest", "cm", "cm"),
    "biceps": Metric("biceps", "cm", "cm"),
    "thigh": Metric("thigh", "cm", "cm"),
}

# Metryki dzienne — `get_daily_health_metrics`.
DAILY_METRICS: dict[str, Metric] = {
    "kcal_in": Metric("kcal_in", "kcal", "kcal"),
    "kcal_active": Metric("kcal_active", "kcal", "kcal"),
    "kcal_basal": Metric("kcal_basal", "kcal", "kcal"),
    "protein": Metric("protein", "g", "g"),
    "fat": Metric("fat", "g", "g"),
    "carbs": Metric("carbs", "g", "g"),
    "steps": Metric("steps", "count", "kroki"),
    "resting_hr": Metric("resting_hr", "bpm", "bpm"),
    "sleep_asleep": Metric("sleep", "asleep", "h"),
    "sleep_deep": Metric("sleep", "deep", "h"),
    "sleep_rem": Metric("sleep", "rem", "h"),
    "sleep_core": Metric("sleep", "core", "h"),
    "sleep_awake": Metric("sleep", "awake", "h"),
    "sleep_in_bed": Metric("sleep", "inBed", "h"),
    "hr_avg": Metric("hr", "avg_bpm", "bpm"),
    "hr_min": Metric("hr", "min_bpm", "bpm"),
    "hr_max": Metric("hr", "max_bpm", "bpm"),
}

# `get_health_trends` przyjmuje dowolną z powyższych.
TREND_METRICS: dict[str, Metric] = {**BODY_METRICS, **DAILY_METRICS}
