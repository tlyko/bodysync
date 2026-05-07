"""Per-mapper integration tests dla wszystkich 13 metryk z fixture
`hae_payload_full.json`. Sprawdzają SK format + attrs key/value per metric."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
TOMEK_SECRET = "tomek-webhook-secret-aaaaaaaaaaaaaaaa"


def _event(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": "2.0",
        "routeKey": "POST /api/health/webhook",
        "headers": {
            "content-type": "application/json",
            "authorization": f"Bearer {TOMEK_SECRET}",
        },
        "body": json.dumps(payload),
        "isBase64Encoded": False,
    }


class _FakeContext:
    aws_request_id = "test-req-id"


def _by_sk(items: list[dict[str, Any]], pattern: str) -> dict[str, Any] | None:
    """Helper — znajdź pierwszy item gdzie SK contains pattern."""
    for item in items:
        if pattern in item["SK"]:
            return item
    return None


@pytest.fixture
def full_payload_response(
    dynamodb_table: Any, ssm_params: None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Wykonuje handler z pełnym fixture, zwraca (response_body, all_DDB_items)."""
    from handlers.health_webhook import handler as h

    payload = json.loads((FIXTURES / "hae_payload_full.json").read_text())
    result = h.handler(_event(payload), _FakeContext())
    body = json.loads(result["body"])

    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#tomek"},
    )["Items"]
    return body, items


def test_full_payload_counts(
    full_payload_response: tuple[dict[str, Any], list[dict[str, Any]]],
) -> None:
    """13 metryk × 1-2 points = 14 total received, all known → 0 skipped."""
    body, items = full_payload_response
    assert body["received"] == 14  # 2 HRV + 12 single-point metrics
    assert body["skipped_unknown"] == 0
    assert body["stored"] == 14


def test_hrv_multipoint(full_payload_response: tuple[dict[str, Any], list[dict[str, Any]]]) -> None:
    _, items = full_payload_response
    hrv_items = [i for i in items if "hrv#" in i["SK"]]
    assert len(hrv_items) == 2
    for item in hrv_items:
        assert item["SK"].startswith("BIOMETRY#2026-05-06#hrv#")
        assert "value_ms" in item


def test_heart_rate_min_avg_max(
    full_payload_response: tuple[dict[str, Any], list[dict[str, Any]]],
) -> None:
    _, items = full_payload_response
    hr = _by_sk(items, "#hr#")
    assert hr is not None
    assert hr["SK"].startswith("BIOMETRY#2026-05-06#hr#")
    assert int(hr["min_bpm"]) == 52
    assert int(hr["avg_bpm"]) == 67
    assert int(hr["max_bpm"]) == 142


def test_resting_heart_rate(
    full_payload_response: tuple[dict[str, Any], list[dict[str, Any]]],
) -> None:
    _, items = full_payload_response
    item = _by_sk(items, "#resting_hr")
    assert item is not None
    assert item["SK"] == "BIOMETRY#2026-05-06#resting_hr"
    assert int(item["bpm"]) == 54


def test_steps(full_payload_response: tuple[dict[str, Any], list[dict[str, Any]]]) -> None:
    """Steps cumulative — 1 hourly bucket w fixture, SK z timestamp."""
    _, items = full_payload_response
    item = _by_sk(items, "#steps#")
    assert item is not None
    assert item["SK"].startswith("BIOMETRY#2026-05-06#steps#")
    assert item["count"] == 8421


def test_active_energy(full_payload_response: tuple[dict[str, Any], list[dict[str, Any]]]) -> None:
    """active_energy cumulative — SK z timestamp, fixture w kJ → DDB w kcal."""
    _, items = full_payload_response
    item = _by_sk(items, "#kcal_active#")
    assert item is not None
    assert item["SK"].startswith("BIOMETRY#2026-05-06#kcal_active#")
    # fixture qty=2038.864 kJ → / 4.184 = 487.3 kcal
    assert abs(float(item["kcal"]) - 487.3) < 0.01


def test_basal_energy(full_payload_response: tuple[dict[str, Any], list[dict[str, Any]]]) -> None:
    _, items = full_payload_response
    item = _by_sk(items, "#kcal_basal#")
    assert item is not None
    assert item["SK"].startswith("BIOMETRY#2026-05-06#kcal_basal#")
    assert float(item["kcal"]) == 1742.8


def test_weight(full_payload_response: tuple[dict[str, Any], list[dict[str, Any]]]) -> None:
    """Snapshot — SK bez timestamp."""
    _, items = full_payload_response
    item = _by_sk(items, "#weight")
    assert item is not None
    assert item["SK"] == "BIOMETRY#2026-05-06#weight"
    assert float(item["kg"]) == 78.4


def test_body_fat(full_payload_response: tuple[dict[str, Any], list[dict[str, Any]]]) -> None:
    _, items = full_payload_response
    item = _by_sk(items, "#body_fat")
    assert item is not None
    assert item["SK"] == "BIOMETRY#2026-05-06#body_fat"
    assert float(item["pct"]) == 18.2


def test_dietary_energy(full_payload_response: tuple[dict[str, Any], list[dict[str, Any]]]) -> None:
    _, items = full_payload_response
    item = _by_sk(items, "#kcal_in#")
    assert item is not None
    assert item["SK"].startswith("BIOMETRY#2026-05-06#kcal_in#")
    assert int(item["kcal"]) == 2341


def test_dietary_macros(full_payload_response: tuple[dict[str, Any], list[dict[str, Any]]]) -> None:
    _, items = full_payload_response
    protein = _by_sk(items, "#protein#")
    fat = _by_sk(items, "#fat#")
    carbs = _by_sk(items, "#carbs#")
    assert protein is not None and fat is not None and carbs is not None
    assert protein["SK"].startswith("BIOMETRY#2026-05-06#protein#")
    assert fat["SK"].startswith("BIOMETRY#2026-05-06#fat#")
    assert carbs["SK"].startswith("BIOMETRY#2026-05-06#carbs#")
    assert float(protein["g"]) == 178.5
    assert float(fat["g"]) == 86.4
    assert float(carbs["g"]) == 245.0


def test_sleep_analysis(full_payload_response: tuple[dict[str, Any], list[dict[str, Any]]]) -> None:
    _, items = full_payload_response
    sleep = _by_sk(items, "#sleep")
    assert sleep is not None
    assert sleep["SK"] == "BIOMETRY#2026-05-06#sleep"
    assert float(sleep["asleep"]) == 8.21
    assert float(sleep["deep"]) == 1.04
    assert float(sleep["rem"]) == 1.85
    assert "sleepStart" in sleep
    assert "sleepEnd" in sleep


def test_sleep_omits_none_fields(dynamodb_table: Any, ssm_params: None) -> None:
    """Minimalny sleep payload (tylko date+source) → DDB row bez None'ów."""
    from handlers.health_webhook import handler as h

    payload = {
        "data": {
            "metrics": [
                {
                    "name": "sleep_analysis",
                    "units": "hr",
                    "data": [
                        {
                            "date": "2026-05-06 08:30:00 +0200",
                            "inBed": 7.5,
                            "asleep": 7.0,
                            "source": "Apple Watch",
                        }
                    ],
                }
            ],
            "workouts": [],
        }
    }
    h.handler(_event(payload), _FakeContext())
    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#tomek"},
    )["Items"]
    sleep = _by_sk(items, "#sleep")
    assert sleep is not None
    # None-valued sub-fields nie zaśmiecają DDB
    assert "core" not in sleep
    assert "deep" not in sleep
    assert "rem" not in sleep
    assert "inBedStart" not in sleep
    assert float(sleep["inBed"]) == 7.5


@pytest.mark.parametrize(
    "metric_name,short_sk,units,raw_qty,expected_kcal",
    [
        # kJ → kcal
        ("active_energy", "#kcal_active#", "kJ", 2038.864, 487.3),
        ("basal_energy_burned", "#kcal_basal#", "kJ", 7291.8752, 1742.8),
        ("dietary_energy", "#kcal_in#", "kJ", 9794.744, 2341.0),
        # kcal passthrough
        ("active_energy", "#kcal_active#", "kcal", 487.3, 487.3),
        ("basal_energy_burned", "#kcal_basal#", "kcal", 1742.8, 1742.8),
        ("dietary_energy", "#kcal_in#", "kcal", 2341.0, 2341.0),
    ],
)
def test_energy_unit_conversion_kj_to_kcal(
    metric_name: str,
    short_sk: str,
    units: str,
    raw_qty: float,
    expected_kcal: float,
    dynamodb_table: Any,
    ssm_params: None,
) -> None:
    """Energy mappery konwertują kJ→kcal (HealthKit SI base unit).

    Driving evidence: live DDB 2026-05-07 kcal_in=3594.89 (raw kJ) / 4.184 =
    859 kcal = match Apple Health UI.
    """
    from handlers.health_webhook import handler as h

    payload = {
        "data": {
            "metrics": [
                {
                    "name": metric_name,
                    "units": units,
                    "data": [
                        {
                            "qty": raw_qty,
                            "date": "2026-05-06 12:00:00 +0200",
                            "source": "Apple Watch",
                        }
                    ],
                }
            ],
            "workouts": [],
        }
    }
    h.handler(_event(payload), _FakeContext())
    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#tomek"},
    )["Items"]
    item = _by_sk(items, short_sk)
    assert item is not None
    assert abs(float(item["kcal"]) - expected_kcal) < 0.01


@pytest.mark.parametrize(
    "metric_name,bad_units",
    [
        ("active_energy", "watts"),
        ("basal_energy_burned", "joules"),
        ("dietary_energy", "BTU"),
        ("protein", "oz"),
        ("total_fat", "lb"),
        ("carbohydrates", "ounce"),
        ("weight_body_mass", "lb"),
        ("step_count", "miles"),
    ],
)
def test_invalid_units_fail_loud_per_metric(
    metric_name: str, bad_units: str, dynamodb_table: Any, ssm_params: None
) -> None:
    """Forward-compat fail-loud: unknown unit dla danej metryki = ValueError
    w mapperze, point pominięty (handler dalej zwraca 200, inne metryki leca).
    """
    from handlers.health_webhook import handler as h

    payload = {
        "data": {
            "metrics": [
                {
                    "name": metric_name,
                    "units": bad_units,
                    "data": [{"qty": 100, "date": "2026-05-06 12:00:00 +0200", "source": "iPhone"}],
                }
            ],
            "workouts": [],
        }
    }
    result = h.handler(_event(payload), _FakeContext())
    body = json.loads(result["body"])
    assert result["statusCode"] == 200
    # Bad units → mapper rzuca, nie zapisuje
    assert body["received"] == 1
    assert body["stored"] == 0
    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#tomek"},
    )["Items"]
    assert len(items) == 0


def test_kj_replay_idempotent_after_conversion(dynamodb_table: Any, ssm_params: None) -> None:
    """Replay payloadu z kJ → drugi call stored=0 (konwersja deterministyczna,
    SK po timestamp identyczny)."""
    from handlers.health_webhook import handler as h

    payload = {
        "data": {
            "metrics": [
                {
                    "name": "dietary_energy",
                    "units": "kJ",
                    "data": [
                        {
                            "qty": 3594.89,
                            "date": "2026-05-06 14:00:00 +0200",
                            "source": "Fitatu",
                        }
                    ],
                }
            ],
            "workouts": [],
        }
    }
    first = h.handler(_event(payload), _FakeContext())
    assert json.loads(first["body"])["stored"] == 1
    second = h.handler(_event(payload), _FakeContext())
    assert json.loads(second["body"])["stored"] == 0


def test_steps_multi_point_hourly_buckets(dynamodb_table: Any, ssm_params: None) -> None:
    """Cumulative model: 3 hourly buckets steps → 3 osobne items, każdy z SK timestamp."""
    from handlers.health_webhook import handler as h

    payload = {
        "data": {
            "metrics": [
                {
                    "name": "step_count",
                    "units": "count",
                    "data": [
                        {"qty": 300, "date": "2026-05-06 09:00:00 +0200", "source": "iPhone"},
                        {"qty": 500, "date": "2026-05-06 12:00:00 +0200", "source": "iPhone"},
                        {"qty": 200, "date": "2026-05-06 18:00:00 +0200", "source": "iPhone"},
                    ],
                }
            ],
            "workouts": [],
        }
    }
    result = h.handler(_event(payload), _FakeContext())
    assert json.loads(result["body"])["stored"] == 3

    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
        ExpressionAttributeValues={":pk": "USER#tomek", ":sk": "BIOMETRY#2026-05-06#steps#"},
    )["Items"]
    assert len(items) == 3
    counts = sorted(int(i["count"]) for i in items)
    assert counts == [200, 300, 500]


def test_cumulative_replay_idempotent(dynamodb_table: Any, ssm_params: None) -> None:
    """Każdy z 7 cumulative mapperów: drugi call tego samego payloadu = stored=0."""
    from handlers.health_webhook import handler as h

    payload = {
        "data": {
            "metrics": [
                {
                    "name": metric,
                    "units": units,
                    "data": [
                        {"qty": 100, "date": "2026-05-06 09:00:00 +0200", "source": "Apple Watch"},
                    ],
                }
                for metric, units in [
                    ("step_count", "count"),
                    ("active_energy", "kcal"),
                    ("basal_energy_burned", "kcal"),
                    ("dietary_energy", "kcal"),
                    ("protein", "g"),
                    ("total_fat", "g"),
                    ("carbohydrates", "g"),
                ]
            ],
            "workouts": [],
        }
    }
    first = h.handler(_event(payload), _FakeContext())
    assert json.loads(first["body"])["stored"] == 7

    second = h.handler(_event(payload), _FakeContext())
    assert json.loads(second["body"])["stored"] == 0


def test_heart_rate_replay_idempotent(dynamodb_table: Any, ssm_params: None) -> None:
    """HR per timestamp = idempotent (multi-point z conditional PutItem)."""
    from handlers.health_webhook import handler as h

    payload = {
        "data": {
            "metrics": [
                {
                    "name": "heart_rate",
                    "units": "bpm",
                    "data": [
                        {
                            "Min": 60,
                            "Avg": 80,
                            "Max": 120,
                            "date": "2026-05-06 12:00:00 +0200",
                            "source": "Apple Watch",
                        }
                    ],
                }
            ],
            "workouts": [],
        }
    }
    first = h.handler(_event(payload), _FakeContext())
    assert json.loads(first["body"])["stored"] == 1
    second = h.handler(_event(payload), _FakeContext())
    # Replay tego samego HR window = NOOP
    assert json.loads(second["body"])["stored"] == 0
