"""Service layer dla GET endpoints — DDB queries + aggregation."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from handlers.api_read.schemas import BiometryDay, MeResponse
from shared.dynamo import get_item, query_by_pk

# Po PR #46 cumulative metrics są multi-point z timestamp w SK; agregacja
# (sum) per dzień idzie tutaj — frontend dostaje single value jak pre-PR-#46.
# Mapping metric_short → value_attr w atrybucie row'u.
CUMULATIVE_METRICS: dict[str, str] = {
    "steps": "count",
    "kcal_in": "kcal",
    "kcal_active": "kcal",
    "kcal_basal": "kcal",
    "protein": "g",
    "fat": "g",
    "carbs": "g",
}


class ProfileNotFoundError(Exception):
    """USER#{id} PROFILE row nie istnieje (user nigdy się nie zalogował)."""


def _to_python(value: Any) -> Any:
    """Decimal → int/float dla JSON response (DDB zwraca Decimal).

    Float'y zaokrąglane do 4 miejsc — usuwa artifacty precyzji typu
    `20.599999999999998` (Decimal('20.6') → float artifact). 4 miejsca
    bezpieczne dla wszystkich obecnych metryk (kg, %, ms, h, bpm).
    """
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return round(float(value), 4)
    if isinstance(value, list):
        return [_to_python(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_python(v) for k, v in value.items()}
    return value


def get_me(user_id: str) -> MeResponse:
    """Zwraca profile usera z DDB. Tworzony przez google_auth handler przy
    pierwszym loginie."""
    item = get_item(f"USER#{user_id}", "PROFILE")
    if item is None:
        raise ProfileNotFoundError(f"USER#{user_id}")
    return MeResponse(
        user_id=user_id,
        email=item["email"],
        name=item.get("name"),
    )


def get_biometry(user_id: str, *, days: int = 7) -> list[BiometryDay]:
    """Pobiera wszystkie BIOMETRY rows dla user_id z ostatnich N dni,
    grupuje po date, agreguje per metric_name.

    Format SK po PR #46 (Sprint 3.5):
      BIOMETRY#YYYY-MM-DD#metric_name              — snapshot (weight, body_fat,
                                                     resting_hr, sleep)
      BIOMETRY#YYYY-MM-DD#metric_name#timestamp    — multi-point (HRV, HR,
                                                     7 cumulative metrics)

    Output shape per metric:
      - cumulative (steps, kcal_*, protein/fat/carbs): suma value_attr przez
        wszystkie hourly buckets, single dict z `samples` count
      - HRV/HR multi-point: lista point'ów (frontend agreguje per-window)
      - snapshot: single dict z atrybutami row'u
    """
    today = datetime.now(UTC).date()
    cutoff_iso = (today - timedelta(days=days - 1)).isoformat()

    items = query_by_pk(f"USER#{user_id}", sk_prefix="BIOMETRY#")

    # Per-day, per-metric — zbieramy buckety. Cumulative dostają specjalny shape
    # `{"_buckets": [attrs, ...]}` żeby agregować w 2. passie.
    by_date: dict[str, dict[str, Any]] = defaultdict(dict)

    for raw in items:
        sk = raw["SK"]
        parts = sk.split("#", 3)
        if len(parts) < 3:
            continue
        sk_date = parts[1]
        metric = parts[2]
        is_multipoint = len(parts) == 4

        if sk_date < cutoff_iso:
            continue

        attrs = {k: _to_python(v) for k, v in raw.items() if k not in ("PK", "SK")}

        if metric in CUMULATIVE_METRICS:
            # Cumulative — sum w 2. passie. Akceptujemy oba shape'y SK
            # (multi-point timestamp jest spec'em po PR #46; single-point
            # to legacy ślad pre-PR-#46 — defense in depth).
            by_date[sk_date].setdefault(metric, {"_buckets": []})["_buckets"].append(attrs)
        elif is_multipoint:
            # HRV / HR — list of points
            existing = by_date[sk_date].get(metric)
            if not isinstance(existing, list):
                by_date[sk_date][metric] = []
            by_date[sk_date][metric].append(attrs)
        else:
            by_date[sk_date][metric] = attrs

    # Pass 2: agreguj cumulative buckety → single dict z sum.
    for metrics_for_day in by_date.values():
        for metric, value_attr in CUMULATIVE_METRICS.items():
            bucket = metrics_for_day.get(metric)
            if not isinstance(bucket, dict) or "_buckets" not in bucket:
                continue
            buckets = bucket["_buckets"]
            # _to_python skonwertował Decimal→int/float w attrs, więc tu sum
            # operuje na float (bezpieczne dla agregatu — i tak idzie do JSON).
            total = sum(float(b.get(value_attr, 0)) for b in buckets)
            # Bierzemy `device`/`source` z ostatniego point'u (debug info).
            last = buckets[-1] if buckets else {}
            metrics_for_day[metric] = {
                # Zaokrąglenie do int — dla kcal/g/count ułamki są szumem
                # (Apple Health UI też pokazuje całkowite).
                value_attr: round(total),
                "samples": len(buckets),
                "device": last.get("device"),
                "source": last.get("source"),
            }

    sorted_dates = sorted(by_date.keys(), reverse=True)
    return [BiometryDay(date=d, metrics=by_date[d]) for d in sorted_dates]


def _today_iso() -> str:
    """Test seam — pozwala mockować bieżącą datę w testach."""
    return date.today().isoformat()
