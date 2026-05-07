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
    _, items = full_payload_response
    item = _by_sk(items, "#steps")
    assert item is not None
    assert item["count"] == 8421


def test_active_energy(full_payload_response: tuple[dict[str, Any], list[dict[str, Any]]]) -> None:
    _, items = full_payload_response
    item = _by_sk(items, "#kcal_active")
    assert item is not None
    assert float(item["kcal"]) == 487.3


def test_basal_energy(full_payload_response: tuple[dict[str, Any], list[dict[str, Any]]]) -> None:
    _, items = full_payload_response
    item = _by_sk(items, "#kcal_basal")
    assert item is not None
    assert float(item["kcal"]) == 1742.8


def test_weight(full_payload_response: tuple[dict[str, Any], list[dict[str, Any]]]) -> None:
    _, items = full_payload_response
    item = _by_sk(items, "#weight")
    assert item is not None
    assert item["SK"] == "BIOMETRY#2026-05-06#weight"
    assert float(item["kg"]) == 78.4


def test_body_fat(full_payload_response: tuple[dict[str, Any], list[dict[str, Any]]]) -> None:
    _, items = full_payload_response
    item = _by_sk(items, "#body_fat")
    assert item is not None
    assert float(item["pct"]) == 18.2


def test_dietary_energy(full_payload_response: tuple[dict[str, Any], list[dict[str, Any]]]) -> None:
    _, items = full_payload_response
    item = _by_sk(items, "#kcal_in")
    assert item is not None
    assert int(item["kcal"]) == 2341


def test_dietary_macros(full_payload_response: tuple[dict[str, Any], list[dict[str, Any]]]) -> None:
    _, items = full_payload_response
    protein = _by_sk(items, "#protein")
    fat = _by_sk(items, "#fat")
    carbs = _by_sk(items, "#carbs")
    assert protein is not None and fat is not None and carbs is not None
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
