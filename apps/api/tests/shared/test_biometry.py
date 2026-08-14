"""Tests dla `shared.biometry` — agregacja BIOMETRY/WORKOUT wyciągnięta
z `handlers/api_read/service.py` (PR MCP #2).

Zachowanie jest już pokryte pośrednio przez `tests/handlers/api_read/`, ale
moduł jedzie teraz do dwóch handlerów (api_read + mcp), więc dostaje własne
testy jednostkowe. Pokrycie: sumowanie cumulative, manual precedence,
multi-point HR, snapshot passthrough, granica okna, PK isolation.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from shared.biometry import LOCAL_TZ


def _today() -> str:
    return datetime.now(LOCAL_TZ).date().isoformat()


def _days_ago(n: int) -> str:
    return (datetime.now(LOCAL_TZ).date() - timedelta(days=n)).isoformat()


@pytest.mark.usefixtures("dynamodb_table")
def test_aggregate_empty_returns_empty_list() -> None:
    """Brak rows → pusta lista, nie None i nie raise."""
    from shared.biometry import aggregate_biometry_days

    assert aggregate_biometry_days("tomek", days=7) == []


def test_cumulative_metric_summed_across_hourly_buckets(dynamodb_table: Any) -> None:
    """3 hourly buckety steps (300+500+200) → jeden dict z count=1000."""
    from shared.biometry import aggregate_biometry_days
    from shared.dynamo import put_item_idempotent

    day = _today()
    for hour, count in [("09", 300), ("12", 500), ("18", 200)]:
        put_item_idempotent(
            "USER#tomek",
            f"BIOMETRY#{day}#steps#{day}T{hour}:00:00+02:00",
            {"count": count, "source": "apple-health", "device": "iPhone"},
        )

    days = aggregate_biometry_days("tomek", days=7)

    assert len(days) == 1
    steps = days[0]["metrics"]["steps"]
    assert steps["count"] == 1000
    assert steps["samples"] == 3
    assert steps["source"] == "apple-health"


def test_manual_entry_overrides_apple_health(dynamodb_table: Any) -> None:
    """Manual precedence: gdy istnieje bucket source=manual, HAE buckety są
    odfiltrowane przed sumowaniem — manual nie dodaje się do HAE."""
    from shared.biometry import aggregate_biometry_days
    from shared.dynamo import put_item_idempotent

    day = _today()
    put_item_idempotent(
        "USER#tomek",
        f"BIOMETRY#{day}#kcal_in#{day}T09:00:00+02:00",
        {"kcal": 800, "source": "apple-health"},
    )
    put_item_idempotent(
        "USER#tomek",
        f"BIOMETRY#{day}#kcal_in#{day}T20:00:00+02:00",
        {"kcal": 2100, "source": "manual"},
    )

    days = aggregate_biometry_days("tomek", days=7)

    kcal_in = days[0]["metrics"]["kcal_in"]
    assert kcal_in["kcal"] == 2100, "manual nadpisuje HAE, nie sumuje się z nim"
    assert kcal_in["samples"] == 1
    assert kcal_in["source"] == "manual"


def test_snapshot_metric_passthrough(dynamodb_table: Any) -> None:
    """Snapshot (weight) bez timestampu w SK → atrybuty przekazane 1:1,
    Decimal skonwertowany na float."""
    from shared.biometry import aggregate_biometry_days
    from shared.dynamo import put_item_idempotent

    day = _today()
    put_item_idempotent(
        "USER#tomek",
        f"BIOMETRY#{day}#weight",
        {"kg": Decimal("84.35"), "source": "apple-health"},
    )

    days = aggregate_biometry_days("tomek", days=7)

    assert days[0]["metrics"]["weight"]["kg"] == 84.35


def test_multipoint_non_cumulative_stays_a_list(dynamodb_table: Any) -> None:
    """HR jest multi-point ale nie cumulative → lista punktów, nie suma."""
    from shared.biometry import aggregate_biometry_days
    from shared.dynamo import put_item_idempotent

    day = _today()
    for hour, bpm in [("09", 62), ("12", 78)]:
        put_item_idempotent(
            "USER#tomek",
            f"BIOMETRY#{day}#hr#{day}T{hour}:00:00+02:00",
            {"bpm": bpm},
        )

    days = aggregate_biometry_days("tomek", days=7)

    hr = days[0]["metrics"]["hr"]
    assert isinstance(hr, list)
    assert {point["bpm"] for point in hr} == {62, 78}


def test_window_boundary_is_inclusive(dynamodb_table: Any) -> None:
    """days=7 obejmuje dzisiaj i 6 dni wstecz; 7 dni wstecz już nie."""
    from shared.biometry import aggregate_biometry_days
    from shared.dynamo import put_item_idempotent

    for offset in (0, 6, 7):
        put_item_idempotent(
            "USER#tomek",
            f"BIOMETRY#{_days_ago(offset)}#weight",
            {"kg": 80 + offset},
        )

    dates = {day["date"] for day in aggregate_biometry_days("tomek", days=7)}

    assert _days_ago(0) in dates
    assert _days_ago(6) in dates, "dolna granica okna musi być inclusive"
    assert _days_ago(7) not in dates, "dzień poza oknem nie może wejść"


def test_days_sorted_newest_first(dynamodb_table: Any) -> None:
    from shared.biometry import aggregate_biometry_days
    from shared.dynamo import put_item_idempotent

    for offset in (0, 1, 2):
        put_item_idempotent("USER#tomek", f"BIOMETRY#{_days_ago(offset)}#weight", {"kg": 80})

    dates = [day["date"] for day in aggregate_biometry_days("tomek", days=7)]

    assert dates == sorted(dates, reverse=True)


def test_pk_isolation_between_two_users(dynamodb_table: Any) -> None:
    """CLAUDE.md: każde query ma PK = USER#{id}. Dane user_b nie mogą
    wyciec do odpowiedzi user_a."""
    from shared.biometry import aggregate_biometry_days
    from shared.dynamo import put_item_idempotent

    day = _today()
    put_item_idempotent("USER#tomek", f"BIOMETRY#{day}#weight", {"kg": 84})
    put_item_idempotent("USER#weronika", f"BIOMETRY#{day}#weight", {"kg": 61})

    tomek = aggregate_biometry_days("tomek", days=7)
    weronika = aggregate_biometry_days("weronika", days=7)

    assert tomek[0]["metrics"]["weight"]["kg"] == 84
    assert weronika[0]["metrics"]["weight"]["kg"] == 61


def test_fetch_workouts_parses_sk_and_sorts_newest_first(dynamodb_table: Any) -> None:
    from shared.biometry import fetch_workouts
    from shared.dynamo import put_item_idempotent

    today, yesterday = _today(), _days_ago(1)
    put_item_idempotent(
        "USER#tomek",
        f"WORKOUT#{yesterday}#trening-a#01",
        {"exercise_name": "Przysiad", "sets": [{"weight_kg": Decimal("100"), "reps": 5}]},
    )
    put_item_idempotent(
        "USER#tomek",
        f"WORKOUT#{today}#trening-b#01",
        {"exercise_name": "Wyciskanie", "sets": [{"weight_kg": Decimal("80"), "reps": 8}]},
    )

    workouts = fetch_workouts("tomek", days=30)

    assert [w["date"] for w in workouts] == [today, yesterday]
    assert workouts[0]["training_slug"] == "trening-b"
    assert workouts[0]["exercise_number"] == "01"
    assert workouts[0]["sets"][0]["weight_kg"] == 80.0


def test_fetch_workouts_pk_isolation(dynamodb_table: Any) -> None:
    from shared.biometry import fetch_workouts
    from shared.dynamo import put_item_idempotent

    day = _today()
    put_item_idempotent("USER#tomek", f"WORKOUT#{day}#trening-a#01", {"exercise_name": "Przysiad"})
    put_item_idempotent("USER#weronika", f"WORKOUT#{day}#trening-a#01", {"exercise_name": "Martwy"})

    assert [w["exercise_name"] for w in fetch_workouts("tomek", days=30)] == ["Przysiad"]
    assert [w["exercise_name"] for w in fetch_workouts("weronika", days=30)] == ["Martwy"]
