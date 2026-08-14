"""Warstwa danych dla narzędzi MCP — DDB → kształt czytelny dla LLM.

Wszystkie odczyty idą przez `shared.biometry`, czyli tę samą agregację co
`GET /api/biometry` (sumowanie cumulative po hourly bucketach, manual
precedence). Zero duplikacji logiki — patrz ADR-010.

Kształt odpowiedzi jest projektowany pod czytelność dla modelu, nie pod
frontend: jawne jednostki, pominięte nulle, daty jako ISO stringi.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from handlers.mcp.metrics import BODY_METRICS, DAILY_METRICS, TREND_METRICS, Metric
from shared.biometry import aggregate_biometry_range, fetch_workouts_range, today_iso

# Powyżej tego zakresu `get_health_trends` przełącza się na średnie tygodniowe.
# Pół roku kcal_active dziennie to ~180 punktów — do przełknięcia, ale dwa lata
# już nie. Tygodniowe średnie tną to ~7x zachowując kształt trendu.
WEEKLY_THRESHOLD_DAYS = 60

# Twardy limit okna — chroni przed `date_from=1970-01-01` zjadającym kontekst
# i przed 1MB cap na DDB Query.
MAX_RANGE_DAYS = 730


class ToolInputError(ValueError):
    """Zły input od modelu — wraca jako `isError: true`, nie jako crash."""


def parse_date(raw: Any, *, field: str) -> date:
    if not isinstance(raw, str):
        raise ToolInputError(
            f"`{field}` musi być stringiem ISO YYYY-MM-DD, dostałem {type(raw).__name__}"
        )
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ToolInputError(f"`{field}` nie jest poprawną datą ISO YYYY-MM-DD: {raw!r}") from exc


def resolve_range(args: dict[str, Any], *, default_days: int) -> tuple[str, str]:
    """Ustala (date_from, date_to) z argumentów narzędzia.

    Oba opcjonalne. Brak `date_to` → dzisiaj. Brak `date_from` → `default_days`
    wstecz od `date_to`. Waliduje kolejność i długość okna.
    """
    date_to = (
        parse_date(args["date_to"], field="date_to")
        if args.get("date_to")
        else date.fromisoformat(today_iso())
    )
    if args.get("date_from"):
        date_from = parse_date(args["date_from"], field="date_from")
    else:
        date_from = date_to - timedelta(days=default_days - 1)

    if date_from > date_to:
        raise ToolInputError(f"`date_from` ({date_from}) jest późniejsze niż `date_to` ({date_to})")
    span = (date_to - date_from).days + 1
    if span > MAX_RANGE_DAYS:
        raise ToolInputError(
            f"zakres {span} dni przekracza limit {MAX_RANGE_DAYS}; zawęź date_from/date_to"
        )
    return date_from.isoformat(), date_to.isoformat()


def _scalar(metrics_for_day: dict[str, Any], metric: Metric) -> float | int | None:
    """Wyciąga skalarną wartość metryki z dnia, albo None gdy brak danych."""
    row = metrics_for_day.get(metric.sk_metric)
    if not isinstance(row, dict):
        return None
    value = row.get(metric.attr)
    return value if isinstance(value, (int, float)) else None


def _round(value: float | int, unit: str) -> float | int:
    """Godziny snu do 2 miejsc, waga/procenty do 1, reszta bez zmian."""
    if unit == "h":
        return round(float(value), 2)
    if unit in ("kg", "%", "cm", "kg/m2"):
        return round(float(value), 1)
    return value


def get_body_composition(user_id: str, args: dict[str, Any]) -> dict[str, Any]:
    """Skład ciała w czasie — sekcja CIAŁO dashboardu."""
    date_from, date_to = resolve_range(args, default_days=90)
    days = aggregate_biometry_range(user_id, date_from=date_from, date_to=date_to)

    entries = []
    for day in days:
        values = {
            name: _round(v, m.unit)
            for name, m in BODY_METRICS.items()
            if (v := _scalar(day["metrics"], m)) is not None
        }
        if values:
            entries.append({"date": day["date"], **values})

    return {
        "range": {"date_from": date_from, "date_to": date_to},
        "units": {name: m.unit for name, m in BODY_METRICS.items()},
        "measurements": entries,
        "note": (
            "Pomiary składu ciała pochodzą z wagi Xiaomi przez Apple Health; obwody "
            "(waist/hips/chest/biceps/thigh) są wpisywane ręcznie i bywają rzadsze."
        ),
    }


def get_daily_health_metrics(user_id: str, args: dict[str, Any]) -> dict[str, Any]:
    """Wszystkie metryki zdrowotne jednego dnia."""
    day_iso = (
        parse_date(args["date"], field="date").isoformat() if args.get("date") else today_iso()
    )
    days = aggregate_biometry_range(user_id, date_from=day_iso, date_to=day_iso)

    metrics_for_day = days[0]["metrics"] if days else {}
    values = {
        name: _round(v, m.unit)
        for name, m in DAILY_METRICS.items()
        if (v := _scalar(metrics_for_day, m)) is not None
    }

    result: dict[str, Any] = {
        "date": day_iso,
        "units": {name: DAILY_METRICS[name].unit for name in values},
        "metrics": values,
    }

    kcal_in = values.get("kcal_in")
    burned = (values.get("kcal_active") or 0) + (values.get("kcal_basal") or 0)
    if kcal_in is not None and burned:
        result["kcal_balance"] = round(kcal_in - burned)
        result["kcal_burned_total"] = round(burned)

    if not values:
        result["note"] = (
            f"Brak danych na {day_iso}. Typowa przyczyna: Health Auto Export nie wysłał "
            "jeszcze dzisiejszej paczki — dane bieżącego dnia bywają niekompletne do wieczora."
        )
    return result


def get_health_trends(user_id: str, args: dict[str, Any]) -> dict[str, Any]:
    """Jedna metryka w czasie. Powyżej 60 dni agreguje do średnich tygodniowych."""
    name = args.get("metric_name")
    if name not in TREND_METRICS:
        raise ToolInputError(
            f"nieznana metryka {name!r}; dostępne: {', '.join(sorted(TREND_METRICS))}"
        )
    metric = TREND_METRICS[name]
    date_from, date_to = resolve_range(args, default_days=30)
    days = aggregate_biometry_range(user_id, date_from=date_from, date_to=date_to)

    points = [
        {"date": day["date"], "value": _round(v, metric.unit)}
        for day in days
        if (v := _scalar(day["metrics"], metric)) is not None
    ]
    points.sort(key=lambda p: p["date"])

    span_days = (date.fromisoformat(date_to) - date.fromisoformat(date_from)).days + 1
    granularity = "daily"
    if span_days > WEEKLY_THRESHOLD_DAYS:
        points = _weekly_averages(points, unit=metric.unit)
        granularity = "weekly"

    result: dict[str, Any] = {
        "metric_name": name,
        "unit": metric.unit,
        "granularity": granularity,
        "range": {"date_from": date_from, "date_to": date_to},
        "points": points,
    }
    if granularity == "weekly":
        result["note"] = (
            f"Zakres {span_days} dni przekracza {WEEKLY_THRESHOLD_DAYS}, więc punkty to "
            "średnie tygodniowe (`date` = poniedziałek tygodnia, `samples` = liczba dni "
            "z danymi). Zawęź zakres, jeśli potrzebujesz wartości dziennych."
        )
    if points:
        values = [p["value"] for p in points]
        result["summary"] = {
            "first": points[0]["value"],
            "last": points[-1]["value"],
            "change": _round(points[-1]["value"] - points[0]["value"], metric.unit),
            "min": min(values),
            "max": max(values),
            "avg": _round(sum(values) / len(values), metric.unit),
        }
    else:
        result["note"] = f"Brak pomiarów `{name}` w zakresie {date_from}..{date_to}."
    return result


def _weekly_averages(points: list[dict[str, Any]], *, unit: str) -> list[dict[str, Any]]:
    """Grupuje punkty dzienne po tygodniach ISO, zwraca średnie."""
    buckets: dict[str, list[float]] = {}
    for point in points:
        day = date.fromisoformat(point["date"])
        monday = (day - timedelta(days=day.weekday())).isoformat()
        buckets.setdefault(monday, []).append(float(point["value"]))
    return [
        {"date": monday, "value": _round(sum(vals) / len(vals), unit), "samples": len(vals)}
        for monday, vals in sorted(buckets.items())
    ]


def get_workouts(user_id: str, args: dict[str, Any]) -> dict[str, Any]:
    """Historia treningów siłowych — ćwiczenia, serie, ciężary, RIR."""
    date_from, date_to = resolve_range(args, default_days=30)
    rows = fetch_workouts_range(user_id, date_from=date_from, date_to=date_to)

    by_date: dict[str, dict[str, Any]] = {}
    for row in rows:
        session = by_date.setdefault(
            row["date"], {"date": row["date"], "training": row["training_slug"], "exercises": []}
        )
        exercise = {
            k: v
            for k, v in row.items()
            if k not in ("date", "training_slug", "exercise_number", "ingested_at")
            and v not in (None, "", [])
        }
        exercise["order"] = row["exercise_number"]
        session["exercises"].append(exercise)

    sessions = sorted(by_date.values(), key=lambda s: s["date"], reverse=True)
    for session in sessions:
        session["exercises"].sort(key=lambda e: e["order"])

    return {
        "range": {"date_from": date_from, "date_to": date_to},
        "sessions": sessions,
        "note": (
            "Serie zapisane jako lista obiektów: `weight_kg` + `reps`, gdzie "
            "`weight_kind: bw` oznacza bodyweight (a `weight_kg` przy nim to dodatkowe "
            "obciążenie). `rir` to reps in reserve."
        ),
    }
