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


def test_kj_replay_overwrite_after_conversion(dynamodb_table: Any, ssm_params: None) -> None:
    """Replay payloadu z kJ → drugi call stored=1 (overwrite cumulative).

    Wartość `kcal` deterministic (`qty / 4.184` reproducible) — overwrite
    daje ten sam result, ale zapisuje (nie skip).
    """
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

    items_after_first = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#tomek"},
    )["Items"]
    assert len(items_after_first) == 1
    kcal_first = items_after_first[0]["kcal"]

    second = h.handler(_event(payload), _FakeContext())
    assert json.loads(second["body"])["stored"] == 1

    items_after_second = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#tomek"},
    )["Items"]
    assert len(items_after_second) == 1
    # Storage value identyczny — żadnego drift'u przy replay
    assert items_after_second[0]["kcal"] == kcal_first


@pytest.mark.parametrize(
    "units_variant",
    ["kJ", "KJ", "kj", "kJ ", " kJ", "Kilojoule", "kilojoule", "KILOJOULE"],
)
def test_units_case_insensitive_kj_conversion(
    units_variant: str, dynamodb_table: Any, ssm_params: None
) -> None:
    """`_normalize_units` (lower + strip) traktuje case/whitespace warianty kJ
    identycznie. Forward-compat na HAE iOS quirks ("kJ "/" KJ"/etc.).
    """
    from handlers.health_webhook import handler as h

    payload = {
        "data": {
            "metrics": [
                {
                    "name": "dietary_energy",
                    "units": units_variant,
                    "data": [
                        {
                            "qty": 4184.0,  # exactly 1000 kcal
                            "date": "2026-05-06 14:00:00 +0200",
                            "source": "Fitatu",
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
    assert len(items) == 1
    assert abs(float(items[0]["kcal"]) - 1000.0) < 0.01


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


def test_cumulative_replay_overwrites(dynamodb_table: Any, ssm_params: None) -> None:
    """Każdy z 7 cumulative mapperów (PR #52 overwrite): drugi call tego
    samego payloadu = stored=7 (overwrite "last snapshot wins").

    Day aggregation HAE wysyła stały SK przez cały dzień; cumulative
    monotonic rośnie w trakcie dnia → musimy nadpisywać.
    """
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

    # Replay = overwrite (cumulative monotonic), NIE skip
    second = h.handler(_event(payload), _FakeContext())
    assert json.loads(second["body"])["stored"] == 7

    # Items count się nie zmienia (overwrite, nie new row)
    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
        ExpressionAttributeValues={":pk": "USER#tomek", ":sk": "BIOMETRY#"},
    )["Items"]
    assert len(items) == 7


def test_cumulative_overwrite_with_higher_value(dynamodb_table: Any, ssm_params: None) -> None:
    """Day aggregation use case: pierwszy export 1559 kcal, drugi export
    1976 kcal (po kolacji) — DDB ma 1976 (nie 1559)."""
    from handlers.health_webhook import handler as h

    def _payload(qty: float) -> dict[str, Any]:
        return {
            "data": {
                "metrics": [
                    {
                        "name": "dietary_energy",
                        "units": "kcal",
                        "data": [
                            {
                                "qty": qty,
                                "date": "2026-05-07 00:00:00 +0200",  # Day agg = midnight
                                "source": "Fitatu",
                            }
                        ],
                    }
                ],
                "workouts": [],
            }
        }

    h.handler(_event(_payload(1559.85)), _FakeContext())
    h.handler(_event(_payload(1976.0)), _FakeContext())

    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
        ExpressionAttributeValues={":pk": "USER#tomek", ":sk": "BIOMETRY#2026-05-07#kcal_in"},
    )["Items"]
    assert len(items) == 1
    assert float(items[0]["kcal"]) == 1976.0


def test_sleep_alias_variants_computed_asleep(dynamodb_table: Any, ssm_params: None) -> None:
    """Regression: payload z `asleepCore`/`asleepREM`/`asleepDeep` (alias variant)
    + brak `asleep` field → DDB row `asleep == sum(core+rem+deep)`.
    """
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
                            "inBed": 8.13,
                            "asleepCore": 4.32,
                            "asleepREM": 1.85,
                            "asleepDeep": 1.04,
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
    # Aliases zmapowały na core/rem/deep
    assert float(sleep["core"]) == 4.32
    assert float(sleep["rem"]) == 1.85
    assert float(sleep["deep"]) == 1.04
    # Computed fallback: asleep = sum(core+rem+deep)
    assert abs(float(sleep["asleep"]) - 7.21) < 0.001


def test_sleep_direct_asleep_field_no_fallback(dynamodb_table: Any, ssm_params: None) -> None:
    """Happy path: payload z bezpośrednim `asleep` → DDB bez computed fallback."""
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
                            "inBed": 8.8,
                            "asleep": 8.21,
                            "core": 4.32,
                            "rem": 1.85,
                            "deep": 1.04,
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
    # Direct field zachowane, fallback nie nadpisuje
    assert float(sleep["asleep"]) == 8.21


def test_sleep_live_bug_asleep_zero_with_substages(dynamodb_table: Any, ssm_params: None) -> None:
    """Regression na live bug: `asleep=0` mimo sub-stages > 0 → fallback computed."""
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
                            "inBed": 8.13,
                            "asleep": 0,
                            "core": 4.32,
                            "rem": 1.85,
                            "deep": 1.04,
                            "awake": 0.59,
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
    assert float(sleep["asleep"]) > 0
    assert abs(float(sleep["asleep"]) - 7.21) < 0.001


def test_sleep_broken_payload_no_storage(dynamodb_table: Any, ssm_params: None) -> None:
    """Broken: `inBed > 0` ale brak wszystkich asleep/core/rem/deep → log error
    i skip storage (nie zaśmiecamy DDB rzędem `inBed-only`)."""
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
                            "inBed": 8.0,
                            "source": "Apple Watch",
                        }
                    ],
                }
            ],
            "workouts": [],
        }
    }
    result = h.handler(_event(payload), _FakeContext())
    body = json.loads(result["body"])
    assert body["received"] == 1
    assert body["stored"] == 0
    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#tomek"},
    )["Items"]
    assert _by_sk(items, "#sleep") is None


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


# ─── lean_body_mass + body_mass_index (Xiaomi Mi Home → Apple Zdrowie) ────


def test_lean_body_mass(dynamodb_table: Any, ssm_params: None) -> None:
    """Snapshot — masa beztłuszczowa w kg, SK bez timestamp."""
    from handlers.health_webhook import handler as h

    payload = {
        "data": {
            "metrics": [
                {
                    "name": "lean_body_mass",
                    "units": "kg",
                    "data": [
                        {
                            "qty": 65.3,
                            "date": "2026-05-06 07:30:00 +0200",
                            "source": "Mi Body Composition Scale",
                        }
                    ],
                }
            ],
            "workouts": [],
        }
    }
    result = h.handler(_event(payload), _FakeContext())
    assert json.loads(result["body"])["stored"] == 1

    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#tomek"},
    )["Items"]
    item = _by_sk(items, "#lean_body_mass")
    assert item is not None
    assert item["SK"] == "BIOMETRY#2026-05-06#lean_body_mass"
    assert float(item["kg"]) == 65.3


def test_lean_body_mass_overwrite(dynamodb_table: Any, ssm_params: None) -> None:
    """Snapshot last-writer-wins: drugi pomiar (65.5 kg) nadpisuje pierwszy
    (65.3 kg). Items count = 1 po obu callach."""
    from handlers.health_webhook import handler as h

    def _payload(qty: float) -> dict[str, Any]:
        return {
            "data": {
                "metrics": [
                    {
                        "name": "lean_body_mass",
                        "units": "kg",
                        "data": [
                            {
                                "qty": qty,
                                "date": "2026-05-06 07:30:00 +0200",
                                "source": "Mi Body Composition Scale",
                            }
                        ],
                    }
                ],
                "workouts": [],
            }
        }

    h.handler(_event(_payload(65.3)), _FakeContext())
    h.handler(_event(_payload(65.5)), _FakeContext())

    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
        ExpressionAttributeValues={
            ":pk": "USER#tomek",
            ":sk": "BIOMETRY#2026-05-06#lean_body_mass",
        },
    )["Items"]
    assert len(items) == 1
    assert float(items[0]["kg"]) == 65.5


def test_body_mass_index(dynamodb_table: Any, ssm_params: None) -> None:
    """BMI snapshot — dimensionless `value`, SK bez timestamp.
    Apple Health wysyła `units: "count"` dla BMI (HKQuantityTypeIdentifierBodyMassIndex)."""
    from handlers.health_webhook import handler as h

    payload = {
        "data": {
            "metrics": [
                {
                    "name": "body_mass_index",
                    "units": "count",
                    "data": [
                        {
                            "qty": 23.4,
                            "date": "2026-05-06 07:30:00 +0200",
                            "source": "Mi Body Composition Scale",
                        }
                    ],
                }
            ],
            "workouts": [],
        }
    }
    result = h.handler(_event(payload), _FakeContext())
    assert json.loads(result["body"])["stored"] == 1

    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#tomek"},
    )["Items"]
    item = _by_sk(items, "#bmi")
    assert item is not None
    assert item["SK"] == "BIOMETRY#2026-05-06#bmi"
    assert float(item["value"]) == 23.4


def test_body_mass_index_no_units(dynamodb_table: Any, ssm_params: None) -> None:
    """BMI dimensionless — HAE może wysyłać bez `units` (None lub puste)."""
    from handlers.health_webhook import handler as h

    payload = {
        "data": {
            "metrics": [
                {
                    "name": "body_mass_index",
                    "data": [
                        {
                            "qty": 23.4,
                            "date": "2026-05-06 07:30:00 +0200",
                            "source": "Mi Body Composition Scale",
                        }
                    ],
                }
            ],
            "workouts": [],
        }
    }
    result = h.handler(_event(payload), _FakeContext())
    assert json.loads(result["body"])["stored"] == 1

    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#tomek"},
    )["Items"]
    item = _by_sk(items, "#bmi")
    assert item is not None
    assert float(item["value"]) == 23.4


def test_lean_body_mass_invalid_unit(dynamodb_table: Any, ssm_params: None) -> None:
    """Fail-loud: `units="lb"` dla lean_body_mass → ValidationError, items=0."""
    from handlers.health_webhook import handler as h

    payload = {
        "data": {
            "metrics": [
                {
                    "name": "lean_body_mass",
                    "units": "lb",
                    "data": [
                        {
                            "qty": 144.0,
                            "date": "2026-05-06 07:30:00 +0200",
                            "source": "Mi Body Composition Scale",
                        }
                    ],
                }
            ],
            "workouts": [],
        }
    }
    result = h.handler(_event(payload), _FakeContext())
    body = json.loads(result["body"])
    assert result["statusCode"] == 200
    assert body["received"] == 1
    assert body["stored"] == 0
    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#tomek"},
    )["Items"]
    assert len(items) == 0


def test_body_mass_index_invalid_unit(dynamodb_table: Any, ssm_params: None) -> None:
    """Fail-loud: `units="kg"` dla BMI (dimensionless) → ValidationError, items=0."""
    from handlers.health_webhook import handler as h

    payload = {
        "data": {
            "metrics": [
                {
                    "name": "body_mass_index",
                    "units": "kg",
                    "data": [
                        {
                            "qty": 23.4,
                            "date": "2026-05-06 07:30:00 +0200",
                            "source": "Mi Body Composition Scale",
                        }
                    ],
                }
            ],
            "workouts": [],
        }
    }
    result = h.handler(_event(payload), _FakeContext())
    body = json.loads(result["body"])
    assert result["statusCode"] == 200
    assert body["received"] == 1
    assert body["stored"] == 0
    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#tomek"},
    )["Items"]
    assert len(items) == 0
