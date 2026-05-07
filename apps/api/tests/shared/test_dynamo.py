"""Tests dla `shared.dynamo` read aggregations (Sprint 3.5 Step 2).

Pokrycie: `sum_metric_today` (happy / empty / multi-point) +
`sum_metric_in_range` (5-day window) + 2-user PK isolation.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest


@pytest.mark.usefixtures("dynamodb_table")
def test_sum_metric_today_empty_returns_zero() -> None:
    """Brak rows tego dnia → Decimal('0'), nie None / nie raise."""
    from shared.dynamo import sum_metric_today

    total = sum_metric_today("tomek", "steps", value_attr="count", today=date(2026, 5, 7))
    assert total == Decimal("0")


def test_sum_metric_today_multi_point(dynamodb_table: Any) -> None:
    """3 hourly bucketów steps (300, 500, 200) → Decimal('1000')."""
    from shared.dynamo import put_item_idempotent, sum_metric_today

    for ts, count in [
        ("2026-05-07T09:00:00+02:00", 300),
        ("2026-05-07T12:00:00+02:00", 500),
        ("2026-05-07T18:00:00+02:00", 200),
    ]:
        put_item_idempotent(
            "USER#tomek",
            f"BIOMETRY#2026-05-07#steps#{ts}",
            {"count": count, "source": "apple-health"},
        )

    total = sum_metric_today("tomek", "steps", value_attr="count", today=date(2026, 5, 7))
    assert total == Decimal("1000")


def test_sum_metric_today_filters_other_metrics(dynamodb_table: Any) -> None:
    """Items z innymi metric short_name w SK nie wpadają do sumy steps."""
    from shared.dynamo import put_item_idempotent, sum_metric_today

    put_item_idempotent(
        "USER#tomek",
        "BIOMETRY#2026-05-07#steps#2026-05-07T09:00:00+02:00",
        {"count": 300},
    )
    put_item_idempotent(
        "USER#tomek",
        "BIOMETRY#2026-05-07#kcal_active#2026-05-07T09:00:00+02:00",
        {"kcal": 100, "count": 999},  # `count` w innej metryce nie powinno wejść
    )

    total = sum_metric_today("tomek", "steps", value_attr="count", today=date(2026, 5, 7))
    assert total == Decimal("300")


def test_sum_metric_today_pk_isolation(dynamodb_table: Any) -> None:
    """User_b nie widzi danych user_a (regression z 2 userami per CLAUDE.md)."""
    from shared.dynamo import put_item_idempotent, sum_metric_today

    put_item_idempotent(
        "USER#tomek",
        "BIOMETRY#2026-05-07#steps#2026-05-07T09:00:00+02:00",
        {"count": 1000},
    )
    put_item_idempotent(
        "USER#weronika",
        "BIOMETRY#2026-05-07#steps#2026-05-07T09:00:00+02:00",
        {"count": 500},
    )

    tomek = sum_metric_today("tomek", "steps", value_attr="count", today=date(2026, 5, 7))
    weronika = sum_metric_today("weronika", "steps", value_attr="count", today=date(2026, 5, 7))
    assert tomek == Decimal("1000")
    assert weronika == Decimal("500")


def test_sum_metric_today_decimal_precision(dynamodb_table: Any) -> None:
    """Energia w kcal (float) → Decimal precision w sumie (np. macro split)."""
    from shared.dynamo import put_item, sum_metric_today

    for ts, kcal in [
        ("2026-05-07T08:00:00+02:00", 487.3),
        ("2026-05-07T13:00:00+02:00", 215.6),
        ("2026-05-07T19:00:00+02:00", 156.05),
    ]:
        put_item(
            "USER#tomek",
            f"BIOMETRY#2026-05-07#kcal_active#{ts}",
            {"kcal": kcal},
        )

    total = sum_metric_today("tomek", "kcal_active", value_attr="kcal", today=date(2026, 5, 7))
    # Decimal arithmetic — bez float roundoff
    assert total == Decimal("487.3") + Decimal("215.6") + Decimal("156.05")


def test_sum_metric_in_range_5_day_window(dynamodb_table: Any) -> None:
    """5-day window z różnymi sumami → dict z 5 kluczami."""
    from shared.dynamo import put_item_idempotent, sum_metric_in_range

    for d, count in [
        ("2026-05-03", 1000),
        ("2026-05-04", 1500),
        # 2026-05-05 brak danych — powinien być 0
        ("2026-05-06", 2000),
        ("2026-05-07", 800),
    ]:
        put_item_idempotent(
            "USER#tomek",
            f"BIOMETRY#{d}#steps#{d}T09:00:00+02:00",
            {"count": count},
        )

    out = sum_metric_in_range(
        "tomek",
        "steps",
        value_attr="count",
        start=date(2026, 5, 3),
        end=date(2026, 5, 7),
    )
    assert set(out.keys()) == {
        "2026-05-03",
        "2026-05-04",
        "2026-05-05",
        "2026-05-06",
        "2026-05-07",
    }
    assert out["2026-05-03"] == Decimal("1000")
    assert out["2026-05-04"] == Decimal("1500")
    assert out["2026-05-05"] == Decimal("0")
    assert out["2026-05-06"] == Decimal("2000")
    assert out["2026-05-07"] == Decimal("800")


def test_sum_metric_in_range_invalid_window(dynamodb_table: Any) -> None:
    """start > end → ValueError (caller bug, fail-loud)."""
    from shared.dynamo import sum_metric_in_range

    with pytest.raises(ValueError, match="start.*>.*end"):
        sum_metric_in_range(
            "tomek",
            "steps",
            value_attr="count",
            start=date(2026, 5, 7),
            end=date(2026, 5, 5),
        )


def test_sum_metric_in_range_single_day(dynamodb_table: Any) -> None:
    """start == end → 1-element dict (inclusive bound)."""
    from shared.dynamo import put_item_idempotent, sum_metric_in_range

    put_item_idempotent(
        "USER#tomek",
        "BIOMETRY#2026-05-07#steps#2026-05-07T09:00:00+02:00",
        {"count": 250},
    )

    out = sum_metric_in_range(
        "tomek",
        "steps",
        value_attr="count",
        start=date(2026, 5, 7),
        end=date(2026, 5, 7),
    )
    assert out == {"2026-05-07": Decimal("250")}
