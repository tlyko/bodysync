"""Tests dla strava_fetcher (DDB Streams trigger → Strava activity fetch)."""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import patch

import boto3
import httpx
import pytest


def _ddb_record(
    *,
    pk: str = "EVENT#strava",
    sk: str = "555#12345#1700000000",
    user_id: str = "tomek",
    object_id: int = 12345,
    object_type: str = "activity",
    aspect_type: str = "create",
    owner_id: int = 11111,
    event_name: str = "INSERT",
) -> dict[str, Any]:
    return {
        "eventID": "abc",
        "eventName": event_name,
        "dynamodb": {
            "Keys": {
                "PK": {"S": pk},
                "SK": {"S": sk},
            },
            "NewImage": {
                "PK": {"S": pk},
                "SK": {"S": sk},
                "user_id": {"S": user_id},
                "object_id": {"N": str(object_id)},
                "object_type": {"S": object_type},
                "aspect_type": {"S": aspect_type},
                "owner_id": {"N": str(owner_id)},
                "event_time": {"N": "1700000000"},
                "subscription_id": {"N": "555"},
            },
        },
    }


class _Ctx:
    aws_request_id = "test-req-id"


@pytest.fixture
def fetcher_ssm(ssm_params: None) -> None:
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
    # Pre-seed tokens valid for tomek (expires far in the future — no refresh)
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
    from shared import ssm as _ssm

    _ssm.clear_cache()


def _activity_response(
    activity_id: int = 12345,
    sport_type: str = "Run",
    *,
    summary_polyline: str | None = "u_p~Fvfbb@aBpHaCnSmDl[",
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": activity_id,
            "name": "Morning Run",
            "sport_type": sport_type,
            "type": "Run",
            "distance": 5234.5,
            "moving_time": 1820,
            "elapsed_time": 1900,
            "total_elevation_gain": 45.0,
            "start_date": "2026-05-08T06:30:00Z",
            "start_date_local": "2026-05-08T08:30:00",
            "timezone": "(GMT+02:00) Europe/Warsaw",
            "calories": 380.5,
            "average_heartrate": 145.0,
            "max_heartrate": 168.0,
            "has_heartrate": True,
            # Sprint 10 A9 — encoded polyline. Test używa krótkiego stringu;
            # Strava real zwraca ~50-200 chars dla biegu 5km.
            "map": {
                "id": f"a{activity_id}",
                "summary_polyline": summary_polyline,
                "polyline": "full-res-not-used",
            }
            if summary_polyline is not None
            else None,
            # extra fields → ignored
            "kudos_count": 0,
        },
    )


def _streams_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "heartrate": {"data": [120, 130, 140], "type": "heartrate"},
            "time": {"data": [0, 60, 120], "type": "time"},
        },
    )


# ─── Defensive skips ──────────────────────────────────────────────────────


@pytest.mark.usefixtures("fetcher_ssm", "dynamodb_table", "s3_bucket")
def test_fetcher_skips_non_event_pk() -> None:
    """CRITICAL: filter_criteria w Terraform też filtruje, ale defense-in-depth."""
    from handlers.strava_fetcher import handler as h

    record = _ddb_record(pk="USER#tomek", sk="BIOMETRY#2026-05-08")
    with patch("handlers.strava_fetcher.service.httpx.Client") as mock_client:
        result = h.handler({"Records": [record]}, _Ctx())

    assert result == {"processed": 0, "skipped": 1, "errors": 0}
    mock_client.assert_not_called()  # NO Strava API call


@pytest.mark.usefixtures("fetcher_ssm", "dynamodb_table", "s3_bucket")
def test_fetcher_skips_modify_event() -> None:
    from handlers.strava_fetcher import handler as h

    record = _ddb_record(event_name="MODIFY")
    result = h.handler({"Records": [record]}, _Ctx())
    assert result == {"processed": 0, "skipped": 1, "errors": 0}


@pytest.mark.usefixtures("fetcher_ssm", "dynamodb_table", "s3_bucket")
def test_fetcher_skips_delete_aspect_type() -> None:
    from handlers.strava_fetcher import handler as h

    record = _ddb_record(aspect_type="delete")
    result = h.handler({"Records": [record]}, _Ctx())
    assert result == {"processed": 0, "skipped": 1, "errors": 0}


@pytest.mark.usefixtures("fetcher_ssm", "dynamodb_table", "s3_bucket")
def test_fetcher_skips_athlete_object_type() -> None:
    """athlete events (np. deauthorize) — nie processujemy w MVP."""
    from handlers.strava_fetcher import handler as h

    record = _ddb_record(object_type="athlete")
    result = h.handler({"Records": [record]}, _Ctx())
    assert result == {"processed": 0, "skipped": 1, "errors": 0}


@pytest.mark.usefixtures("fetcher_ssm", "dynamodb_table", "s3_bucket")
def test_fetcher_skips_404_activity_deletion_race() -> None:
    """User usunął activity zanim fetcher dostał event → skip silent."""
    from handlers.strava_fetcher import handler as h

    record = _ddb_record()
    with patch(
        "handlers.strava_fetcher.service.httpx.Client.get",
        return_value=httpx.Response(404),
    ):
        result = h.handler({"Records": [record]}, _Ctx())
    assert result == {"processed": 0, "skipped": 1, "errors": 0}


# ─── Happy path ───────────────────────────────────────────────────────────


@pytest.mark.usefixtures("fetcher_ssm")
def test_fetcher_persists_activity_to_ddb_and_streams_to_s3(
    dynamodb_table: Any, s3_bucket: Any
) -> None:
    from handlers.strava_fetcher import handler as h

    record = _ddb_record()

    def _get_route(*args: Any, **kwargs: Any) -> httpx.Response:
        # First GET = activity, second = streams
        url = args[0] if args else kwargs.get("url", "")
        if "streams" in url:
            return _streams_response()
        return _activity_response()

    with patch(
        "handlers.strava_fetcher.service.httpx.Client.get",
        side_effect=_get_route,
    ):
        result = h.handler({"Records": [record]}, _Ctx())

    assert result == {"processed": 1, "skipped": 0, "errors": 0}

    # DDB row pod USER#tomek ACTIVITY#12345
    item = dynamodb_table.get_item(Key={"PK": "USER#tomek", "SK": "ACTIVITY#12345"})["Item"]
    assert int(item["strava_id"]) == 12345
    assert item["sport_type"] == "Run"
    assert item["streams_s3_key"] == "strava/streams/tomek/12345.json"
    # Sprint 10 A9 — polyline persisted dla mapy thumbnail
    assert item["summary_polyline"] == "u_p~Fvfbb@aBpHaCnSmDl["

    # S3 object exists
    obj = s3_bucket.get_object(
        Bucket="bodysync-data-test-bucket", Key="strava/streams/tomek/12345.json"
    )
    payload = json.loads(obj["Body"].read())
    assert "heartrate" in payload


@pytest.mark.usefixtures("fetcher_ssm")
def test_fetcher_persists_activity_when_streams_fail(dynamodb_table: Any, s3_bucket: Any) -> None:
    """Streams 500 → activity persistowane bez streams_s3_key (best-effort)."""
    from handlers.strava_fetcher import handler as h

    record = _ddb_record()

    def _get_route(*args: Any, **kwargs: Any) -> httpx.Response:
        url = args[0] if args else kwargs.get("url", "")
        if "streams" in url:
            return httpx.Response(500)
        return _activity_response()

    with patch("handlers.strava_fetcher.service.httpx.Client.get", side_effect=_get_route):
        result = h.handler({"Records": [record]}, _Ctx())

    assert result == {"processed": 1, "skipped": 0, "errors": 0}
    item = dynamodb_table.get_item(Key={"PK": "USER#tomek", "SK": "ACTIVITY#12345"})["Item"]
    assert "streams_s3_key" not in item


@pytest.mark.usefixtures("fetcher_ssm")
def test_fetcher_skips_polyline_for_no_gps_sport(dynamodb_table: Any, s3_bucket: Any) -> None:
    """Sprint 10 A9 — sport bez GPS (np. WeightTraining) Strava zwraca
    map=null lub map.summary_polyline=null. Fetcher NIE zapisuje attr."""
    from handlers.strava_fetcher import handler as h

    record = _ddb_record()

    def _get_route(*args: Any, **kwargs: Any) -> httpx.Response:
        url = args[0] if args else kwargs.get("url", "")
        if "streams" in url:
            return httpx.Response(500)  # don't care for streams here
        return _activity_response(summary_polyline=None)  # no GPS

    with patch("handlers.strava_fetcher.service.httpx.Client.get", side_effect=_get_route):
        result = h.handler({"Records": [record]}, _Ctx())

    assert result["processed"] == 1
    item = dynamodb_table.get_item(Key={"PK": "USER#tomek", "SK": "ACTIVITY#12345"})["Item"]
    assert "summary_polyline" not in item


@pytest.mark.usefixtures("fetcher_ssm")
def test_fetcher_refreshes_token_when_expired(dynamodb_table: Any, s3_bucket: Any) -> None:
    """Tokens expired in past → refresh przed fetch + persist nowych tokens."""
    # Override tokens jako expired
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
    from shared import ssm as _ssm

    _ssm.clear_cache()

    from handlers.strava_fetcher import handler as h

    record = _ddb_record()

    refresh_response = httpx.Response(
        200,
        json={
            "access_token": "NEW_AT",
            "refresh_token": "NEW_RT",
            "expires_at": int(time.time()) + 21600,
        },
    )

    def _get_route(*args: Any, **kwargs: Any) -> httpx.Response:
        url = args[0] if args else kwargs.get("url", "")
        if "streams" in url:
            return _streams_response()
        return _activity_response()

    with (
        patch(
            "handlers.strava_fetcher.service.httpx.Client.post",
            return_value=refresh_response,
        ),
        patch("handlers.strava_fetcher.service.httpx.Client.get", side_effect=_get_route),
    ):
        result = h.handler({"Records": [record]}, _Ctx())

    assert result == {"processed": 1, "skipped": 0, "errors": 0}

    # Verify nowe tokens w SSM
    fresh = boto3.client("ssm", region_name="eu-west-1").get_parameter(
        Name="/bodysync/strava/tomek/tokens", WithDecryption=True
    )["Parameter"]["Value"]
    fresh_data = json.loads(fresh)
    assert fresh_data["access_token"] == "NEW_AT"
    assert fresh_data["refresh_token"] == "NEW_RT"


@pytest.mark.usefixtures("fetcher_ssm")
def test_fetcher_batch_one_failure_does_not_block_others(
    dynamodb_table: Any, s3_bucket: Any
) -> None:
    """3 records: jeden non-Strava PK (skip), jeden 500 (error), jeden happy."""
    from handlers.strava_fetcher import handler as h

    records = [
        _ddb_record(pk="USER#tomek", sk="BIOMETRY#x"),  # skip
        _ddb_record(sk="555#12345#1", object_id=12345),  # error 500
        _ddb_record(sk="555#67890#2", object_id=67890),  # happy
    ]

    call_count = 0

    def _get_route(*args: Any, **kwargs: Any) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        url = args[0] if args else kwargs.get("url", "")
        if "12345" in url and "streams" not in url:
            return httpx.Response(500)
        if "streams" in url:
            return _streams_response()
        return _activity_response(activity_id=67890)

    with patch("handlers.strava_fetcher.service.httpx.Client.get", side_effect=_get_route):
        result = h.handler({"Records": records}, _Ctx())

    assert result["skipped"] == 1
    assert result["errors"] == 1
    assert result["processed"] == 1

    # Trzeci record (67890) został zapisany mimo error w drugim
    item = dynamodb_table.get_item(Key={"PK": "USER#tomek", "SK": "ACTIVITY#67890"})["Item"]
    assert int(item["strava_id"]) == 67890
