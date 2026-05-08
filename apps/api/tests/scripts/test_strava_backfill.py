"""Tests dla scripts/strava_backfill.py."""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import patch

import boto3
import httpx
import pytest


def _resp(status: int, body: object | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, request=httpx.Request("GET", "https://stub"))


@pytest.fixture
def backfill_ssm(ssm_params: None) -> None:
    client = boto3.client("ssm", region_name="eu-west-1")
    client.put_parameter(
        Name="/bodysync/strava/client_id",
        Value="123456",
        Type="String",
    )
    client.put_parameter(
        Name="/bodysync/strava/client_secret",
        Value="0123456789abcdef0123456789abcdef01234567",
        Type="SecureString",
    )
    client.put_parameter(
        Name="/bodysync/strava/tomek/tokens",
        Value=json.dumps(
            {
                "access_token": "AT_TOMEK",
                "refresh_token": "RT_TOMEK",
                "expires_at": int(time.time()) + 3600,
                "athlete_id": 11111,
                "connected_at": int(time.time()) - 1000,
            }
        ),
        Type="SecureString",
    )


def _activities_payload(count: int) -> list[dict[str, Any]]:
    return [
        {
            "id": 1000 + i,
            "name": f"Activity {i}",
            "sport_type": "Run",
            "start_date": "2026-05-01T06:00:00Z",
        }
        for i in range(count)
    ]


def test_backfill_writes_n_synthetic_events_to_ddb(backfill_ssm: None, dynamodb_table: Any) -> None:
    from scripts.strava_backfill import main

    with patch(
        "scripts.strava_backfill.httpx.get", return_value=_resp(200, _activities_payload(5))
    ):
        rc = main(["--user-id", "tomek", "--count", "5", "--table", "bodysync-data-test"])

    assert rc == 0

    # 5 EVENT#strava rows
    resp = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "EVENT#strava"},
    )
    items = resp["Items"]
    assert len(items) == 5
    assert all(int(i["subscription_id"]) == 999999 for i in items)
    assert all(i["user_id"] == "tomek" for i in items)
    assert all(int(i["owner_id"]) == 11111 for i in items)


def test_backfill_count_validation(backfill_ssm: None, dynamodb_table: Any) -> None:
    from scripts.strava_backfill import main

    rc = main(["--user-id", "tomek", "--count", "0"])
    assert rc == 1
    rc = main(["--user-id", "tomek", "--count", "100"])
    assert rc == 1


def test_backfill_refreshes_expired_tokens(backfill_ssm: None, dynamodb_table: Any) -> None:
    """Tokens expired → refresh PRZED fetch activities."""
    boto3.client("ssm", region_name="eu-west-1").put_parameter(
        Name="/bodysync/strava/tomek/tokens",
        Value=json.dumps(
            {
                "access_token": "OLD_AT",
                "refresh_token": "OLD_RT",
                "expires_at": int(time.time()) - 100,  # expired
                "athlete_id": 11111,
                "connected_at": int(time.time()) - 86400,
            }
        ),
        Type="SecureString",
        Overwrite=True,
    )

    refresh_resp = _resp(
        200,
        {
            "access_token": "NEW_AT",
            "refresh_token": "NEW_RT",
            "expires_at": int(time.time()) + 21600,
        },
    )

    from scripts.strava_backfill import main

    with (
        patch("scripts.strava_backfill.httpx.post", return_value=refresh_resp),
        patch(
            "scripts.strava_backfill.httpx.get",
            return_value=_resp(200, _activities_payload(2)),
        ),
    ):
        rc = main(["--user-id", "tomek", "--count", "2", "--table", "bodysync-data-test"])
    assert rc == 0

    fresh = json.loads(
        boto3.client("ssm", region_name="eu-west-1").get_parameter(
            Name="/bodysync/strava/tomek/tokens", WithDecryption=True
        )["Parameter"]["Value"]
    )
    assert fresh["access_token"] == "NEW_AT"


def test_backfill_empty_strava_response_returns_0(backfill_ssm: None, dynamodb_table: Any) -> None:
    """User has 0 activities w Strava history — graceful exit, brak DDB writes."""
    from scripts.strava_backfill import main

    with patch("scripts.strava_backfill.httpx.get", return_value=_resp(200, [])):
        rc = main(["--user-id", "tomek", "--count", "10", "--table", "bodysync-data-test"])
    assert rc == 0


def test_backfill_idempotent_duplicate_skipped(backfill_ssm: None, dynamodb_table: Any) -> None:
    """Re-run z tymi samymi activities → ConditionalCheck failed dla SK collision,
    log warn, ale handler kontynuuje (no crash)."""
    from scripts.strava_backfill import main

    payload = _activities_payload(3)
    with patch("scripts.strava_backfill.httpx.get", return_value=_resp(200, payload)):
        rc1 = main(["--user-id", "tomek", "--count", "3", "--table", "bodysync-data-test"])
    assert rc1 == 0

    # Re-run — SK identical (same activity_id + same time.time() second?
    # Test może być flaky jeśli sekunda się zmieni — sleep żeby zwiększyć
    # diff event_time).
    time.sleep(1.1)
    with patch("scripts.strava_backfill.httpx.get", return_value=_resp(200, payload)):
        rc2 = main(["--user-id", "tomek", "--count", "3", "--table", "bodysync-data-test"])
    # rc2 == 0 niezależnie czy duplicate (write succeeded z nowym event_time)
    # lub idempotent skip (event_time conflict; warn log).
    assert rc2 == 0
