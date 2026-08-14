"""Tests dla narzędzi MCP — kształt danych, granularność trendów, PK isolation."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

USER = "tomek"


def _today() -> str:
    from shared.biometry import LOCAL_TZ

    return datetime.now(LOCAL_TZ).date().isoformat()


def _days_ago(n: int) -> str:
    from shared.biometry import LOCAL_TZ

    return (datetime.now(LOCAL_TZ).date() - timedelta(days=n)).isoformat()


def _put_weight(user: str, day: str, kg: str) -> None:
    from shared.dynamo import put_item_idempotent

    put_item_idempotent(
        f"USER#{user}", f"BIOMETRY#{day}#weight", {"kg": Decimal(kg), "source": "apple-health"}
    )


@pytest.mark.usefixtures("dynamodb_table")
def test_body_composition_collects_all_metrics() -> None:
    from handlers.mcp import tools
    from shared.dynamo import put_item_idempotent

    day = _today()
    put_item_idempotent("USER#tomek", f"BIOMETRY#{day}#weight", {"kg": Decimal("73.7")})
    put_item_idempotent("USER#tomek", f"BIOMETRY#{day}#bmi", {"value": Decimal("23.5")})
    put_item_idempotent("USER#tomek", f"BIOMETRY#{day}#body_fat", {"pct": Decimal("20.6")})
    put_item_idempotent(
        "USER#tomek", f"BIOMETRY#{day}#waist", {"cm": Decimal("80"), "source": "manual"}
    )

    out = tools.call("get_body_composition", {}, user_id=USER)

    entry = out["measurements"][0]
    assert entry["date"] == day
    assert entry["weight"] == 73.7
    assert entry["bmi"] == 23.5
    assert entry["body_fat"] == 20.6
    assert entry["waist"] == 80.0
    assert out["units"]["body_fat"] == "%"


@pytest.mark.usefixtures("dynamodb_table")
def test_daily_metrics_computes_kcal_balance() -> None:
    """Bilans = spożyte − (aktywne + spoczynkowe), mirror KcalBalanceCard."""
    from handlers.mcp import tools
    from shared.dynamo import put_item_idempotent

    day = _today()
    for metric, kcal in [("kcal_in", 2200), ("kcal_active", 700), ("kcal_basal", 1800)]:
        put_item_idempotent(
            "USER#tomek", f"BIOMETRY#{day}#{metric}#{day}T12:00:00+02:00", {"kcal": kcal}
        )

    out = tools.call("get_daily_health_metrics", {"date": day}, user_id=USER)

    assert out["metrics"]["kcal_in"] == 2200
    assert out["kcal_burned_total"] == 2500
    assert out["kcal_balance"] == -300


@pytest.mark.usefixtures("dynamodb_table")
def test_daily_metrics_explains_empty_day() -> None:
    """Pusty dzień musi tłumaczyć DLACZEGO, żeby model nie uznał braku za zero."""
    from handlers.mcp import tools

    out = tools.call("get_daily_health_metrics", {"date": _days_ago(3)}, user_id=USER)

    assert out["metrics"] == {}
    assert "Health Auto Export" in out["note"]


@pytest.mark.usefixtures("dynamodb_table")
def test_sleep_phases_exposed_as_separate_metrics() -> None:
    from handlers.mcp import tools
    from shared.dynamo import put_item_idempotent

    day = _today()
    put_item_idempotent(
        "USER#tomek",
        f"BIOMETRY#{day}#sleep",
        {"asleep": Decimal("9.016"), "deep": Decimal("1.25"), "rem": Decimal("3.116")},
    )

    out = tools.call("get_daily_health_metrics", {"date": day}, user_id=USER)

    assert out["metrics"]["sleep_asleep"] == 9.02
    assert out["metrics"]["sleep_deep"] == 1.25
    assert out["metrics"]["sleep_rem"] == 3.12


@pytest.mark.usefixtures("dynamodb_table")
def test_trends_daily_granularity_with_summary() -> None:
    from handlers.mcp import tools

    for offset, kg in [(0, "80.0"), (1, "80.5"), (2, "81.0")]:
        _put_weight("tomek", _days_ago(offset), kg)

    out = tools.call("get_health_trends", {"metric_name": "weight"}, user_id=USER)

    assert out["granularity"] == "daily"
    assert [p["date"] for p in out["points"]] == sorted(p["date"] for p in out["points"])
    assert out["summary"]["first"] == 81.0
    assert out["summary"]["last"] == 80.0
    assert out["summary"]["change"] == -1.0


@pytest.mark.usefixtures("dynamodb_table")
def test_trends_switch_to_weekly_above_threshold() -> None:
    """Powyżej 60 dni punkty są agregowane tygodniowo — inaczej pół roku
    kcal_active zalałoby kontekst modelu."""
    from handlers.mcp import tools

    for offset in range(0, 90, 3):
        _put_weight("tomek", _days_ago(offset), "80.0")

    out = tools.call(
        "get_health_trends",
        {"metric_name": "weight", "date_from": _days_ago(89), "date_to": _today()},
        user_id=USER,
    )

    assert out["granularity"] == "weekly"
    assert all("samples" in p for p in out["points"])
    assert len(out["points"]) < 30, "agregacja tygodniowa musi realnie zmniejszyć liczbę punktów"
    assert "60" in out["note"]


@pytest.mark.usefixtures("dynamodb_table")
def test_trends_unknown_metric_lists_available() -> None:
    """Komunikat błędu ma wymienić dostępne metryki, żeby model mógł poprawić
    wywołanie zamiast zgadywać."""
    from handlers.mcp import tools
    from handlers.mcp.service import ToolInputError

    with pytest.raises(ToolInputError) as exc:
        tools.call("get_health_trends", {"metric_name": "hrv"}, user_id=USER)

    assert "weight" in str(exc.value)


@pytest.mark.usefixtures("dynamodb_table")
def test_range_validation_rejects_reversed_and_oversized() -> None:
    from handlers.mcp import tools
    from handlers.mcp.service import ToolInputError

    with pytest.raises(ToolInputError, match="późniejsze"):
        tools.call(
            "get_body_composition", {"date_from": _today(), "date_to": _days_ago(5)}, user_id=USER
        )

    with pytest.raises(ToolInputError, match="limit"):
        tools.call(
            "get_body_composition", {"date_from": "2000-01-01", "date_to": _today()}, user_id=USER
        )

    with pytest.raises(ToolInputError, match="ISO"):
        tools.call("get_body_composition", {"date_from": "wczoraj"}, user_id=USER)


@pytest.mark.usefixtures("dynamodb_table")
def test_workouts_grouped_by_session_and_ordered() -> None:
    from handlers.mcp import tools
    from shared.dynamo import put_item_idempotent

    day = _today()
    put_item_idempotent(
        "USER#tomek",
        f"WORKOUT#{day}#trening-a#02",
        {"exercise_name": "Wiosłowanie", "sets": [{"weight_kg": Decimal("60"), "reps": 8}]},
    )
    put_item_idempotent(
        "USER#tomek",
        f"WORKOUT#{day}#trening-a#01",
        {"exercise_name": "Przysiad", "sets": [{"weight_kg": Decimal("100"), "reps": 5}], "rir": 2},
    )

    out = tools.call("get_workouts", {}, user_id=USER)

    session = out["sessions"][0]
    assert session["training"] == "trening-a"
    assert [e["exercise_name"] for e in session["exercises"]] == ["Przysiad", "Wiosłowanie"]
    assert session["exercises"][0]["rir"] == 2


@pytest.mark.usefixtures("dynamodb_table")
def test_every_tool_isolates_users() -> None:
    """CLAUDE.md: dane user_b nie mogą wyciec do odpowiedzi user_a."""
    from handlers.mcp import tools

    day = _today()
    _put_weight("tomek", day, "84.0")
    _put_weight("weronika", day, "61.0")

    tomek = tools.call("get_body_composition", {}, user_id="tomek")
    weronika = tools.call("get_body_composition", {}, user_id="weronika")

    assert tomek["measurements"][0]["weight"] == 84.0
    assert weronika["measurements"][0]["weight"] == 61.0

    trend = tools.call("get_health_trends", {"metric_name": "weight"}, user_id="weronika")
    assert [p["value"] for p in trend["points"]] == [61.0]
