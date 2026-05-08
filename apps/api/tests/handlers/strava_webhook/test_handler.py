"""Tests dla GET + POST /api/strava/webhook."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import boto3
import pytest


def _get_event(qs: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "version": "2.0",
        "routeKey": "GET /api/strava/webhook",
        "rawPath": "/api/strava/webhook",
        "requestContext": {"http": {"method": "GET"}},
        "headers": {},
        "cookies": [],
        "queryStringParameters": qs or {},
        "isBase64Encoded": False,
    }


def _post_event(body: dict[str, Any] | str | None) -> dict[str, Any]:
    if isinstance(body, dict):
        raw = json.dumps(body)
    elif body is None:
        raw = ""
    else:
        raw = body
    return {
        "version": "2.0",
        "routeKey": "POST /api/strava/webhook",
        "rawPath": "/api/strava/webhook",
        "requestContext": {"http": {"method": "POST"}},
        "headers": {"content-type": "application/json"},
        "cookies": [],
        "queryStringParameters": {},
        "body": raw,
        "isBase64Encoded": False,
    }


class _Ctx:
    aws_request_id = "test-req-id"


VERIFY_TOKEN = "v" * 48  # ≥32 chars
WRONG_TOKEN = "w" * 48
REAL_SUB_ID = 555
SYNTHETIC_SUB_ID = 999999  # = SYNTHETIC_SUBSCRIPTION_ID


@pytest.fixture
def webhook_ssm(ssm_params: None) -> None:
    """Pre-seed verify_token + subscription_id + athlete-to-user."""
    client = boto3.client("ssm", region_name="eu-west-1")
    client.put_parameter(
        Name="/bodysync/strava/verify_token",
        Value=VERIFY_TOKEN,
        Type="SecureString",
        Overwrite=True,
    )
    client.put_parameter(
        Name="/bodysync/strava/subscription_id",
        Value=str(REAL_SUB_ID),
        Type="String",
    )
    client.put_parameter(
        Name="/bodysync/strava/athlete-to-user",
        Value=json.dumps({"11111": "tomek", "22222": "weronika"}),
        Type="String",
    )
    from shared import ssm as _ssm

    _ssm.clear_cache()


# ─── GET handshake ─────────────────────────────────────────────────────────


@pytest.mark.usefixtures("webhook_ssm", "dynamodb_table")
def test_handshake_valid_token_echoes_challenge() -> None:
    from handlers.strava_webhook import handler as h

    result = h.handler(
        _get_event(
            {
                "hub.mode": "subscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "abc-123",
            }
        ),
        _Ctx(),
    )
    assert result["statusCode"] == 200
    assert json.loads(result["body"]) == {"hub.challenge": "abc-123"}


@pytest.mark.usefixtures("webhook_ssm", "dynamodb_table")
def test_handshake_wrong_token_returns_403() -> None:
    from handlers.strava_webhook import handler as h

    result = h.handler(
        _get_event(
            {
                "hub.mode": "subscribe",
                "hub.verify_token": WRONG_TOKEN,
                "hub.challenge": "x",
            }
        ),
        _Ctx(),
    )
    assert result["statusCode"] == 403


@pytest.mark.usefixtures("webhook_ssm", "dynamodb_table")
def test_handshake_missing_params_returns_400() -> None:
    from handlers.strava_webhook import handler as h

    # Brak hub.challenge
    result = h.handler(
        _get_event({"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN}),
        _Ctx(),
    )
    assert result["statusCode"] == 400


@pytest.mark.usefixtures("webhook_ssm", "dynamodb_table")
def test_handshake_wrong_mode_returns_400() -> None:
    from handlers.strava_webhook import handler as h

    result = h.handler(
        _get_event(
            {
                "hub.mode": "unsubscribe",
                "hub.verify_token": VERIFY_TOKEN,
                "hub.challenge": "x",
            }
        ),
        _Ctx(),
    )
    assert result["statusCode"] == 400


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_handshake_503_when_verify_token_placeholder() -> None:
    from handlers.strava_webhook import handler as h

    boto3.client("ssm", region_name="eu-west-1").put_parameter(
        Name="/bodysync/strava/verify_token",
        Value="PLACEHOLDER",
        Type="SecureString",
        Overwrite=True,
    )
    from shared import ssm as _ssm

    _ssm.clear_cache()
    result = h.handler(
        _get_event(
            {
                "hub.mode": "subscribe",
                "hub.verify_token": "anything",
                "hub.challenge": "x",
            }
        ),
        _Ctx(),
    )
    assert result["statusCode"] == 503


# ─── POST event ────────────────────────────────────────────────────────────


def _valid_event_body(
    subscription_id: int = REAL_SUB_ID,
    object_id: int = 12345,
    owner_id: int = 11111,
    aspect_type: str = "create",
    event_time: int = 1700000000,
) -> dict[str, Any]:
    return {
        "object_type": "activity",
        "object_id": object_id,
        "aspect_type": aspect_type,
        "owner_id": owner_id,
        "subscription_id": subscription_id,
        "event_time": event_time,
        "updates": {},
    }


@pytest.mark.usefixtures("webhook_ssm")
def test_event_writes_to_ddb_with_ttl(dynamodb_table: Any) -> None:
    from handlers.strava_webhook import handler as h
    from shared.strava import EVENT_TTL_SECONDS

    body = _valid_event_body(event_time=1700000000)
    result = h.handler(_post_event(body), _Ctx())
    assert result["statusCode"] == 200

    row = dynamodb_table.get_item(
        Key={
            "PK": "EVENT#strava",
            "SK": f"{REAL_SUB_ID}#12345#1700000000",
        }
    )["Item"]
    assert row["user_id"] == "tomek"
    assert int(row["owner_id"]) == 11111
    assert row["aspect_type"] == "create"
    assert int(row["ttl"]) == 1700000000 + EVENT_TTL_SECONDS


@pytest.mark.usefixtures("webhook_ssm")
def test_event_duplicate_idempotent(dynamodb_table: Any) -> None:
    """Drugi POST z tym samym (subscription, object, event_time) → no second write."""
    from handlers.strava_webhook import handler as h

    body = _valid_event_body(event_time=1700000000)
    h.handler(_post_event(body), _Ctx())

    # Mutate non-key field — sprawdzić czy idempotent guard zabezpiecza.
    body2 = {**body, "aspect_type": "update"}
    result = h.handler(_post_event(body2), _Ctx())
    assert result["statusCode"] == 200

    row = dynamodb_table.get_item(
        Key={"PK": "EVENT#strava", "SK": f"{REAL_SUB_ID}#12345#1700000000"}
    )["Item"]
    # Pierwszy write zwyciężył (aspect_type='create'), drugi był ignored.
    assert row["aspect_type"] == "create"


@pytest.mark.usefixtures("webhook_ssm", "dynamodb_table")
def test_event_unknown_subscription_dropped_silently() -> None:
    from handlers.strava_webhook import handler as h

    body = _valid_event_body(subscription_id=88888)  # != REAL_SUB_ID, != SYNTHETIC
    result = h.handler(_post_event(body), _Ctx())
    assert result["statusCode"] == 200  # silent drop, no oracle


@pytest.mark.usefixtures("webhook_ssm")
def test_event_unknown_subscription_does_not_write(dynamodb_table: Any) -> None:
    from handlers.strava_webhook import handler as h

    body = _valid_event_body(subscription_id=88888, event_time=1700000000)
    h.handler(_post_event(body), _Ctx())
    row = dynamodb_table.get_item(Key={"PK": "EVENT#strava", "SK": "88888#12345#1700000000"})
    assert "Item" not in row


@pytest.mark.usefixtures("webhook_ssm", "dynamodb_table")
def test_event_unknown_owner_dropped_silently() -> None:
    from handlers.strava_webhook import handler as h

    body = _valid_event_body(owner_id=77777)  # not in athlete-to-user map
    result = h.handler(_post_event(body), _Ctx())
    assert result["statusCode"] == 200


@pytest.mark.usefixtures("webhook_ssm")
def test_event_synthetic_subscription_with_known_owner_accepted(
    dynamodb_table: Any,
) -> None:
    """Replay path: SYNTHETIC_SUBSCRIPTION_ID accepted dla testów."""
    from handlers.strava_webhook import handler as h

    body = _valid_event_body(
        subscription_id=SYNTHETIC_SUB_ID, owner_id=22222, event_time=1700000099
    )
    result = h.handler(_post_event(body), _Ctx())
    assert result["statusCode"] == 200

    row = dynamodb_table.get_item(
        Key={
            "PK": "EVENT#strava",
            "SK": f"{SYNTHETIC_SUB_ID}#12345#1700000099",
        }
    )["Item"]
    assert row["user_id"] == "weronika"


@pytest.mark.usefixtures("webhook_ssm", "dynamodb_table")
def test_event_malformed_body_returns_200() -> None:
    """Strava nie retry-uje malformed; zwracamy 200 + log warn."""
    from handlers.strava_webhook import handler as h

    result = h.handler(_post_event("{not-json"), _Ctx())
    assert result["statusCode"] == 200


@pytest.mark.usefixtures("webhook_ssm", "dynamodb_table")
def test_event_missing_required_field_returns_200() -> None:
    from handlers.strava_webhook import handler as h

    bad = {"object_type": "activity"}  # missing owner_id, subscription_id, etc.
    result = h.handler(_post_event(bad), _Ctx())
    assert result["statusCode"] == 200  # silent — Pydantic ValidationError


@pytest.mark.usefixtures("webhook_ssm", "dynamodb_table")
def test_event_does_not_log_payload(caplog: pytest.LogCaptureFixture) -> None:
    """Audit guard — log records nie powinny zawierać raw payload (PII)."""
    from handlers.strava_webhook import handler as h

    body = _valid_event_body(event_time=int(time.time()))
    body["secret_marker"] = "SHOULD_NOT_LOG_THIS_FIELD"

    with caplog.at_level(logging.DEBUG, logger="strava_webhook"):
        h.handler(_post_event(body), _Ctx())

    full = (
        " ".join(r.getMessage() for r in caplog.records)
        + " "
        + " ".join(str(getattr(r, k, "")) for r in caplog.records for k in vars(r))
    )
    assert "SHOULD_NOT_LOG_THIS_FIELD" not in full


@pytest.mark.usefixtures("webhook_ssm", "dynamodb_table")
def test_method_not_allowed_returns_405() -> None:
    from handlers.strava_webhook import handler as h

    event = _post_event(_valid_event_body())
    event["requestContext"]["http"]["method"] = "DELETE"
    result = h.handler(event, _Ctx())
    assert result["statusCode"] == 405


@pytest.mark.usefixtures("webhook_ssm", "dynamodb_table")
def test_event_unconfigured_subscription_id_falls_back_to_minus_1() -> None:
    """Gdy SSM ma PLACEHOLDER (przed Step 7 CLI) — wszystkie events rejected
    poza synthetic. Defensive: nie crashujemy."""
    from handlers.strava_webhook import handler as h

    boto3.client("ssm", region_name="eu-west-1").put_parameter(
        Name="/bodysync/strava/subscription_id",
        Value="PLACEHOLDER",
        Type="String",
        Overwrite=True,
    )
    from shared import ssm as _ssm

    _ssm.clear_cache()
    boto3.client("ssm", region_name="eu-west-1").put_parameter(
        Name="/bodysync/strava/verify_token",
        Value=VERIFY_TOKEN,
        Type="SecureString",
        Overwrite=True,
    )
    boto3.client("ssm", region_name="eu-west-1").put_parameter(
        Name="/bodysync/strava/athlete-to-user",
        Value=json.dumps({"11111": "tomek"}),
        Type="String",
        Overwrite=True,
    )
    _ssm.clear_cache()

    body = _valid_event_body(subscription_id=REAL_SUB_ID)
    result = h.handler(_post_event(body), _Ctx())
    assert result["statusCode"] == 200  # rejected silently — sub != -1
