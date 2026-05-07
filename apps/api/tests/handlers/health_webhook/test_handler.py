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
WERONIKA_SECRET = "weronika-webhook-secret-bbbbbbbbbbbbbb"


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
    # 2 HRV (z timestampem) + 1 steps (też z timestampem — cumulative model)
    assert sks[0].startswith("BIOMETRY#2026-05-06#hrv#")
    assert sks[1].startswith("BIOMETRY#2026-05-06#hrv#")
    assert sks[2].startswith("BIOMETRY#2026-05-06#steps#")


@pytest.mark.usefixtures("ssm_params")
def test_happy_path_weronika(dynamodb_table: Any) -> None:
    """Bearer = WERONIKA_SECRET → all writes pod USER#weronika, nic pod USER#tomek."""
    from handlers.health_webhook import handler as h

    result = h.handler(_event(_load_minimal_payload(), bearer=WERONIKA_SECRET), _FakeContext())
    assert result["statusCode"] == 200

    tomek = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#tomek"},
    )["Items"]
    weronika = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#weronika"},
    )["Items"]
    assert len(tomek) == 0
    assert len(weronika) == 3


@pytest.mark.usefixtures("ssm_params")
def test_pk_isolation_two_users(dynamodb_table: Any) -> None:
    """Sec audit: writes per user nie mieszają się."""
    from handlers.health_webhook import handler as h

    h.handler(_event(_load_minimal_payload(), bearer=TOMEK_SECRET), _FakeContext())
    h.handler(_event(_load_minimal_payload(), bearer=WERONIKA_SECRET), _FakeContext())

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
        Name="/bodysync/health-auto-export/webhook_secret_weronika",
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
def test_replay_hrv_idempotent_steps_overwrite(dynamodb_table: Any) -> None:
    """Replay całego payloadu (po PR #52):
    - HRV (multi-point z timestampem różnym per reading) — idempotent skip
    - Steps (cumulative monotonic) — overwrite "last snapshot wins"
    """
    from handlers.health_webhook import handler as h

    payload = _load_minimal_payload()
    first = h.handler(_event(payload), _FakeContext())
    assert json.loads(first["body"])["stored"] == 3

    second = h.handler(_event(payload), _FakeContext())
    body = json.loads(second["body"])
    assert second["statusCode"] == 200
    assert body["received"] == 3
    # 2 HRV idempotent (różne timestamps w SK) + 1 steps overwrite = 1 stored
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
def test_s3_archive_on_success(dynamodb_table: Any, s3_bucket: Any) -> None:
    """Po pomyślnym ingest raw body ląduje w S3 pod expected key prefix."""
    from handlers.health_webhook import handler as h

    payload = _load_minimal_payload()
    result = h.handler(_event(payload), _FakeContext())
    assert result["statusCode"] == 200

    objects = s3_bucket.list_objects_v2(
        Bucket="bodysync-data-test-bucket",
        Prefix="raw/health-auto-export/tomek/",
    )
    contents = objects.get("Contents", [])
    assert len(contents) == 1
    key = contents[0]["Key"]
    # raw/health-auto-export/tomek/YYYY/MM/DD/{iso}.json
    assert key.startswith("raw/health-auto-export/tomek/")
    assert key.endswith(".json")

    # Body == raw JSON request
    obj = s3_bucket.get_object(Bucket="bodysync-data-test-bucket", Key=key)
    body = obj["Body"].read().decode("utf-8")
    assert json.loads(body) == payload


@pytest.mark.usefixtures("ssm_params")
def test_s3_archive_failure_does_not_block_ingest(
    dynamodb_table: Any, s3_bucket: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3 outage → handler i tak zwraca 200 i przepuszcza ingest do DDB."""
    from shared import s3 as _s3

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("simulated S3 outage")

    monkeypatch.setattr(_s3, "archive_raw_payload", _boom)

    from handlers.health_webhook import handler as h

    payload = _load_minimal_payload()
    result = h.handler(_event(payload), _FakeContext())
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    # Ingest mimo S3 fail
    assert body["received"] == 3
    assert body["stored"] == 3


@pytest.mark.usefixtures("ssm_params")
def test_s3_archive_skipped_without_bucket_env(
    dynamodb_table: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Brak `RAW_BUCKET_NAME` → log error, ingest dalej leci, brak crash."""
    monkeypatch.delenv("RAW_BUCKET_NAME", raising=False)

    from handlers.health_webhook import handler as h

    payload = _load_minimal_payload()
    result = h.handler(_event(payload), _FakeContext())
    assert result["statusCode"] == 200
    assert json.loads(result["body"])["stored"] == 3


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
    assert items[0]["SK"].startswith("BIOMETRY#2026-05-06#steps#")
