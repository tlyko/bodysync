"""Definicje narzędzi MCP — schematy JSON + dispatch do warstwy danych.

Schematy pisane ręcznie jako dict literale zamiast generowane z type hintów.
To świadomy koszt decyzji z ADR-010: generowanie schematów wymaga pydantica,
a pydantic to zmierzone ~490 ms cold startu. Przy czterech narzędziach
read-only ręczne schematy to ~40 linii.

Opisy narzędzi i parametrów są tym, na podstawie czego model decyduje KIEDY
sięgnąć po narzędzie — piszemy je pod tę decyzję, nie jako dokumentację API.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from handlers.mcp import service

_DATE_RANGE_PROPS: dict[str, Any] = {
    "date_from": {
        "type": "string",
        "description": "Początek zakresu, ISO YYYY-MM-DD (włącznie). Pominięty = wyliczony wstecz od date_to.",
    },
    "date_to": {
        "type": "string",
        "description": "Koniec zakresu, ISO YYYY-MM-DD (włącznie). Pominięty = dzisiaj.",
    },
}

_METRIC_NAMES = sorted(
    {
        "weight",
        "bmi",
        "body_fat",
        "lean_body_mass",
        "waist",
        "hips",
        "chest",
        "biceps",
        "thigh",
        "kcal_in",
        "kcal_active",
        "kcal_basal",
        "protein",
        "fat",
        "carbs",
        "steps",
        "resting_hr",
        "sleep_asleep",
        "sleep_deep",
        "sleep_rem",
        "sleep_core",
        "sleep_awake",
        "sleep_in_bed",
        "hr_avg",
        "hr_min",
        "hr_max",
    }
)

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_body_composition",
        "title": "Skład ciała",
        "description": (
            "Historia składu ciała: masa ciała, BMI, procent tkanki tłuszczowej, beztłuszczowa "
            "masa ciała oraz obwody (talia, biodra, klatka, biceps, udo). Użyj gdy pytanie "
            "dotyczy wagi, sylwetki, redukcji, przyrostu masy albo postępów w czasie. "
            "Domyślnie ostatnie 90 dni."
        ),
        "inputSchema": {
            "type": "object",
            "properties": dict(_DATE_RANGE_PROPS),
            "additionalProperties": False,
        },
    },
    {
        "name": "get_daily_health_metrics",
        "title": "Metryki zdrowotne dnia",
        "description": (
            "Komplet metryk z jednego dnia: kalorie spożyte i spalone (aktywne + spoczynkowe), "
            "makroskładniki, kroki, sen z podziałem na fazy (deep/REM/core/awake), tętno "
            "spoczynkowe oraz min/avg/max tętna. Dolicza bilans kaloryczny. Użyj gdy pytanie "
            "dotyczy konkretnego dnia, wypoczęcia, regeneracji albo bilansu. Domyślnie dzisiaj."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Dzień w formacie ISO YYYY-MM-DD. Pominięty = dzisiaj.",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_health_trends",
        "title": "Trend metryki",
        "description": (
            "Przebieg jednej metryki w czasie wraz z podsumowaniem (pierwsza, ostatnia, zmiana, "
            "min, max, średnia). Użyj gdy pytanie dotyczy kierunku zmian, porównania okresów albo "
            "'jak mi szło przez ostatni miesiąc'. Zakresy powyżej 60 dni są automatycznie "
            "agregowane do średnich tygodniowych, żeby nie zalewać odpowiedzi punktami. "
            "Domyślnie ostatnie 30 dni."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "metric_name": {
                    "type": "string",
                    "enum": _METRIC_NAMES,
                    "description": "Nazwa metryki do prześledzenia.",
                },
                **_DATE_RANGE_PROPS,
            },
            "required": ["metric_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_workouts",
        "title": "Treningi siłowe",
        "description": (
            "Historia wykonanych treningów siłowych: ćwiczenia w kolejności, serie z ciężarem "
            "i liczbą powtórzeń, RIR oraz notatki. Użyj gdy pytanie dotyczy siłowni, progresji "
            "w konkretnym ćwiczeniu, objętości treningowej albo tego, co było robione na ostatnim "
            "treningu. NIE zawiera aktywności cardio ze Stravy. Domyślnie ostatnie 30 dni."
        ),
        "inputSchema": {
            "type": "object",
            "properties": dict(_DATE_RANGE_PROPS),
            "additionalProperties": False,
        },
    },
]

_DISPATCH: dict[str, Callable[[str, dict[str, Any]], dict[str, Any]]] = {
    "get_body_composition": service.get_body_composition,
    "get_daily_health_metrics": service.get_daily_health_metrics,
    "get_health_trends": service.get_health_trends,
    "get_workouts": service.get_workouts,
}


def call(name: str, arguments: dict[str, Any], *, user_id: str) -> dict[str, Any]:
    """Wykonuje narzędzie. Rzuca `service.ToolInputError` przy złym inpucie,
    `KeyError` przy nieznanej nazwie."""
    return _DISPATCH[name](user_id, arguments)
