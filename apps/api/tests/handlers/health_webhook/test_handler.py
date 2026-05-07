"""Tests dla handlers.health_webhook (Sprint 3 PR A — scaffold).

PR A coverage: 2 metryki (HRV multi-point + steps single-point).
PR B doda heart_rate / sleep / kcal / weight / body_fat / dietary mappers
+ test_mappers.py per-mapper unit tests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import boto3
import pytest

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"

TOMEK_SECRET = "tomek-webhook-secret-aaaaaaaaaaaaaaaa"
PARTNER_SECRET = "partner-webhook-secret-bbbbbbbbbbbbbb"


def _event(
    body: str | dict[str, Any] | None, *, bearer: str | None = TOMEK_SECRET
) -> dict[str, Any]:
    if body is None:
        raw = ""
    elif isinstance(body, str):
        raw = body
    else:
        raw = json.dumps(body)
    headers: dict[str, str] = {"content-type": "application/json"}
    if bearer is not None:
        headers["authorization"] = f"Bearer {bearer}"
    return {
        "version": "2.0",
        "routeKey": "POST /api/health/webhook",
        "headers": headers,
        "body": raw,
        "isBase64Encoded": False,
    }


class _FakeContext:
    aws_request_id = "test-req-id"


def _load_minimal_payload() -> dict[str, Any]:
    return json.loads((FIXTURES / "hae_payload_minimal.json").read_text())


@pytest.mark.usefixtures("ssm_params")
def test_happy_path_minimal_payload(dynamodb_table: Any) -> None:
    """2 HRV points + 1 steps point → 3 stored, PROFILE pod USER#tomek."""
    from handlers.health_webhook import handler as h

    payload = _load_minimal_payload()
    result = h.handler(_event(payload), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body == {"received": 3, "stored": 3, "skipped_unknown": 0}

    # Wszystkie items pod USER#tomek (Bearer = TOMEK_SECRET)
    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#tomek"},
    )["Items"]
    assert len(items) == 3
    sks = sorted(i["SK"] for i in items)
    # 2 HRV (z timestampem) + 1 steps (bez timestampu)
    assert sks[0].startswith("BIOMETRY#2026-05-06#hrv#")
    assert sks[1].startswith("BIOMETRY#2026-05-06#hrv#")
    assert sks[2] == "BIOMETRY#2026-05-06#steps"


@pytest.mark.usefixtures("ssm_params")
def test_happy_path_partner(dynamodb_table: Any) -> None:
    """Bearer = PARTNER_SECRET → all writes pod USER#partner, nic pod USER#tomek."""
    from handlers.health_webhook import handler as h

    result = h.handler(_event(_load_minimal_payload(), bearer=PARTNER_SECRET), _FakeContext())
    assert result["statusCode"] == 200

    tomek = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#tomek"},
    )["Items"]
    partner = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#partner"},
    )["Items"]
    assert len(tomek) == 0
    assert len(partner) == 3


@pytest.mark.usefixtures("ssm_params")
def test_pk_isolation_two_users(dynamodb_table: Any) -> None:
    """Sec audit: writes per user nie mieszają się."""
    from handlers.health_webhook import handler as h

    h.handler(_event(_load_minimal_payload(), bearer=TOMEK_SECRET), _FakeContext())
    h.handler(_event(_load_minimal_payload(), bearer=PARTNER_SECRET), _FakeContext())

    tomek = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#tomek"},
    )["Items"]
    assert all(i["PK"] == "USER#tomek" for i in tomek)
    assert len(tomek) == 3


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_401_missing_authorization() -> None:
    from handlers.health_webhook import handler as h

    result = h.handler(_event(_load_minimal_payload(), bearer=None), _FakeContext())
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_401_invalid_bearer() -> None:
    from handlers.health_webhook import handler as h

    result = h.handler(
        _event(_load_minimal_payload(), bearer="totally-bogus-32-chars-xxxxxxxxxxxx"),
        _FakeContext(),
    )
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_401_malformed_authorization_header() -> None:
    from handlers.health_webhook import handler as h

    # Brak prefix'u "Bearer "
    event = _event(_load_minimal_payload(), bearer=None)
    event["headers"]["authorization"] = "JustATokenWithoutBearerPrefix"
    result = h.handler(event, _FakeContext())
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("dynamodb_table")
def test_401_when_secrets_are_placeholder() -> None:
    """SSM secrets = "PLACEHOLDER" (Terraform default) → fail-fast → 401.
    Bez tego placeholder pasowałby do Bearer="PLACEHOLDER" → fałszywy login."""
    from handlers.health_webhook import handler as h

    client = boto3.client("ssm", region_name="eu-west-1")
    client.put_parameter(
        Name="/bodysync/health-auto-export/webhook_secret_tomek",
        Value="PLACEHOLDER",
        Type="SecureString",
    )
    client.put_parameter(
        Name="/bodysync/health-auto-export/webhook_secret_partner",
        Value="PLACEHOLDER",
        Type="SecureString",
    )
    from shared import ssm as _ssm

    _ssm.clear_cache()

    result = h.handler(_event(_load_minimal_payload(), bearer="PLACEHOLDER"), _FakeContext())
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_400_invalid_json() -> None:
    from handlers.health_webhook import handler as h

    result = h.handler(_event("{not json}"), _FakeContext())
    assert result["statusCode"] == 400


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_400_missing_data_field() -> None:
    """Pydantic ValidationError na top-level (brak `data`) → 400."""
    from handlers.health_webhook import handler as h

    result = h.handler(_event({"metrics": []}), _FakeContext())
    assert result["statusCode"] == 400
    body = json.loads(result["body"])
    assert "details" in body


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_400_does_not_leak_user_input() -> None:
    """Sec audit C2: ValidationError details NIE zawiera `input` field."""
    from handlers.health_webhook import handler as h

    secret_marker = "SHOULD_NOT_LEAK_zz12"
    result = h.handler(
        _event({"data": secret_marker}), _FakeContext()
    )  # data jako string zamiast obiektu
    assert result["statusCode"] == 400
    body_str = result["body"]
    assert secret_marker not in body_str


@pytest.mark.usefixtures("ssm_params")
def test_replay_hrv_multipoint_idempotent(dynamodb_table: Any) -> None:
    """Replay tego samego HRV point = idempotent skip (conditional PutItem
    na BIOMETRY#date#hrv#timestamp). Steps overwrite (last-writer-wins)."""
    from handlers.health_webhook import handler as h

    payload = _load_minimal_payload()
    first = h.handler(_event(payload), _FakeContext())
    assert json.loads(first["body"])["stored"] == 3

    second = h.handler(_event(payload), _FakeContext())
    body = json.loads(second["body"])
    assert second["statusCode"] == 200
    # 2 HRV points idempotent → stored=0 (conditional skip)
    # 1 steps point overwrites → stored=1 (put_item w/o condition zwraca True)
    assert body["received"] == 3
    assert body["stored"] == 1


@pytest.mark.usefixtures("ssm_params")
def test_unknown_metric_skipped(dynamodb_table: Any) -> None:
    """Nowy iOS metric → log warn + skip, nie 400 (forward compat)."""
    from handlers.health_webhook import handler as h

    payload = {
        "data": {
            "metrics": [
                {
                    "name": "unknown_alien_metric",
                    "units": "ufo",
                    "data": [{"qty": 42, "date": "2026-05-06 12:00:00 +0200", "source": "X"}],
                }
            ],
            "workouts": [],
        }
    }
    result = h.handler(_event(payload), _FakeContext())
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body == {"received": 0, "stored": 0, "skipped_unknown": 1}

    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#tomek"},
    )["Items"]
    assert len(items) == 0


@pytest.mark.usefixtures("ssm_params")
def test_workouts_silently_dropped(dynamodb_table: Any) -> None:
    """MVP: workouts logujemy ale nie writeujemy do DDB (Strava jest source)."""
    from handlers.health_webhook import handler as h

    payload = {
        "data": {
            "metrics": [],
            "workouts": [
                {
                    "name": "Bieganie",
                    "start": "2026-05-06 18:00:00 +0200",
                    "end": "2026-05-06 19:00:00 +0200",
                }
            ],
        }
    }
    result = h.handler(_event(payload), _FakeContext())
    assert result["statusCode"] == 200
    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#tomek"},
    )["Items"]
    assert len(items) == 0


@pytest.mark.usefixtures("ssm_params")
def test_warsaw_local_date_grouping(dynamodb_table: Any) -> None:
    """Punkt z 2026-05-06 01:30 +0200 → SK z 2026-05-06 (Warsaw local),
    NIE 2026-05-05 (UTC by sygestionał wczorajszy dzień)."""
    from handlers.health_webhook import handler as h

    payload = {
        "data": {
            "metrics": [
                {
                    "name": "step_count",
                    "units": "count",
                    "data": [{"qty": 100, "date": "2026-05-06 01:30:00 +0200", "source": "iPhone"}],
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
    assert items[0]["SK"] == "BIOMETRY#2026-05-06#steps"
