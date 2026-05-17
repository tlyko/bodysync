"""Tests dla handlers.me_delete — DELETE /api/me/account (RODO Art. 17).

Cascade scenarios: DDB partition wipe, S3 raw cleanup, SSM per-user delete,
JSON-map prune. PK isolation regression: delete tomka NIE rusza weroniki.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import boto3
import pytest

_CSRF_TEST_TOKEN = "test-csrf-token-deterministic"


def _event(
    cookie: str | None,
    *,
    body: dict[str, Any] | None = None,
    raw_body: str | None = None,
    csrf: bool = True,
) -> dict[str, Any]:
    cookies: list[str] = [cookie] if cookie else []
    headers: dict[str, str] = {"content-type": "application/json"}
    if csrf:
        cookies.append(f"bodysync_csrf={_CSRF_TEST_TOKEN}")
        headers["x-csrf-token"] = _CSRF_TEST_TOKEN
    if raw_body is not None:
        body_str: str | None = raw_body
    else:
        body_str = json.dumps(body) if body is not None else None
    return {
        "version": "2.0",
        "routeKey": "DELETE /api/me/account",
        "rawPath": "/api/me/account",
        "requestContext": {"http": {"method": "DELETE"}},
        "headers": headers,
        "cookies": cookies,
        "body": body_str,
        "isBase64Encoded": False,
    }


class _FakeContext:
    aws_request_id = "test-req-id"


def _mint_test_jwt(user_id: str) -> str:
    from shared.auth import mint_jwt

    return mint_jwt(user_id)


def _seed_ddb_user(table: Any, user_id: str) -> None:
    pk = f"USER#{user_id}"
    table.put_item(Item={"PK": pk, "SK": "PROFILE", "email": f"{user_id}@example.com"})
    table.put_item(
        Item={
            "PK": pk,
            "SK": "BIOMETRY#2026-05-01#weight",
            "kg": Decimal("82.5"),
        }
    )
    table.put_item(
        Item={
            "PK": pk,
            "SK": "ACTIVITY#42",
            "sport_type": "Run",
        }
    )


def _seed_s3(s3_client: Any, bucket: str, user_id: str) -> None:
    s3_client.put_object(
        Bucket=bucket,
        Key=f"raw/health-auto-export/{user_id}/2026/05/01/00.json",
        Body=b'{"x":1}',
    )
    s3_client.put_object(
        Bucket=bucket,
        Key=f"raw/health-auto-export/{user_id}/2026/05/02/01.json",
        Body=b'{"x":2}',
    )
    s3_client.put_object(
        Bucket=bucket,
        Key=f"strava/streams/{user_id}/99999.json",
        Body=b'{"a":1}',
    )


def _seed_ssm(ssm_client: Any, user_id: str, athlete_id: int) -> None:
    ssm_client.put_parameter(
        Name=f"/bodysync/strava/{user_id}/tokens",
        Value=json.dumps({"access_token": "x", "refresh_token": "y"}),
        Type="SecureString",
        Overwrite=True,
    )
    ssm_client.put_parameter(
        Name=f"/bodysync/{user_id}/training-sheet-id",
        Value="sheet-abc",
        Type="String",
        Overwrite=True,
    )
    ssm_client.put_parameter(
        Name=f"/bodysync/{user_id}/training-sheet-tab",
        Value="Arkusz1",
        Type="String",
        Overwrite=True,
    )
    # athlete-to-user map (single shared param) — seed with `user_id` entry.
    map_existing = json.dumps({str(athlete_id): user_id, "11111": "weronika"}, sort_keys=True)
    ssm_client.put_parameter(
        Name="/bodysync/strava/athlete-to-user",
        Value=map_existing,
        Type="String",
        Overwrite=True,
    )
    # allowed_emails — seed with user entry.
    allowlist = [
        {"email": "tlyko94@gmail.com", "user_id": "tomek"},
        {"email": "weronika@example.com", "user_id": "weronika"},
    ]
    ssm_client.put_parameter(
        Name="/bodysync/auth/allowed_emails",
        Value=json.dumps(allowlist),
        Type="String",
        Overwrite=True,
    )


# ─── Auth + confirm guards ────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_missing_cookie_returns_401() -> None:
    from handlers.me_delete import handler as h

    result = h.handle(_event(None, body={"confirm": "DELETE"}), _FakeContext())
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_invalid_jwt_returns_401() -> None:
    from handlers.me_delete import handler as h

    result = h.handle(
        _event("bodysync_session=not-a-jwt", body={"confirm": "DELETE"}), _FakeContext()
    )
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_missing_csrf_returns_403() -> None:
    from handlers.me_delete import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(_event(cookie, body={"confirm": "DELETE"}, csrf=False), _FakeContext())
    assert result["statusCode"] == 403


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_missing_confirm_returns_422() -> None:
    from handlers.me_delete import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(_event(cookie, body={}), _FakeContext())
    assert result["statusCode"] == 422


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_wrong_confirm_phrase_returns_422() -> None:
    from handlers.me_delete import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(_event(cookie, body={"confirm": "delete"}), _FakeContext())
    assert result["statusCode"] == 422


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_invalid_json_body_returns_422() -> None:
    from handlers.me_delete import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(_event(cookie, raw_body="{not json"), _FakeContext())
    assert result["statusCode"] == 422


# ─── Happy cascade ────────────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params")
def test_happy_cascade_wipes_all_user_data(dynamodb_table: Any, s3_bucket: Any) -> None:
    from handlers.me_delete import handler as h

    _seed_ddb_user(dynamodb_table, "tomek")
    _seed_s3(s3_bucket, "bodysync-data-test-bucket", "tomek")
    ssm = boto3.client("ssm", region_name="eu-west-1")
    _seed_ssm(ssm, "tomek", athlete_id=12345)

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(_event(cookie, body={"confirm": "DELETE"}), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    counts = body["deleted"]
    assert counts["ddb_rows"] == 3
    assert counts["s3_objects"] == 3
    # 4 per-user SSM keys: Strava tokens, HAE webhook_secret_tomek (seedowany
    # w conftest.ssm_params fixture), training-sheet-id, training-sheet-tab.
    assert counts["ssm_user_keys"] == 4
    assert counts["athlete_map_entries"] == 1
    assert counts["allowed_emails_entries"] == 1

    # DDB partition empty.
    remaining = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#tomek"},
    )["Items"]
    assert remaining == []

    # S3 prefixes empty.
    hae_list = s3_bucket.list_objects_v2(
        Bucket="bodysync-data-test-bucket", Prefix="raw/health-auto-export/tomek/"
    )
    assert hae_list.get("KeyCount", 0) == 0
    strava_list = s3_bucket.list_objects_v2(
        Bucket="bodysync-data-test-bucket", Prefix="strava/streams/tomek/"
    )
    assert strava_list.get("KeyCount", 0) == 0

    # SSM per-user keys gone.
    for path in (
        "/bodysync/strava/tomek/tokens",
        "/bodysync/tomek/training-sheet-id",
        "/bodysync/tomek/training-sheet-tab",
    ):
        with pytest.raises(ssm.exceptions.ParameterNotFound):
            ssm.get_parameter(Name=path)

    # athlete-to-user map z tomek entry usunięte (weronika została).
    map_raw = ssm.get_parameter(Name="/bodysync/strava/athlete-to-user")["Parameter"]["Value"]
    map_obj = json.loads(map_raw)
    assert map_obj == {"11111": "weronika"}

    # allowed_emails — tomek dropped.
    allowlist_raw = ssm.get_parameter(Name="/bodysync/auth/allowed_emails")["Parameter"]["Value"]
    allowlist = json.loads(allowlist_raw)
    assert all(entry["user_id"] != "tomek" for entry in allowlist)
    assert any(entry["user_id"] == "weronika" for entry in allowlist)


# ─── Idempotency: re-call zwraca counts 0 ─────────────────────────────────


@pytest.mark.usefixtures("ssm_params")
def test_idempotent_recall_returns_zero_counts(dynamodb_table: Any, s3_bucket: Any) -> None:
    """Drugie DELETE od razu po pierwszym → 200 z wszystkimi countami 0."""
    from handlers.me_delete import handler as h

    _seed_ddb_user(dynamodb_table, "tomek")
    _seed_s3(s3_bucket, "bodysync-data-test-bucket", "tomek")
    ssm = boto3.client("ssm", region_name="eu-west-1")
    _seed_ssm(ssm, "tomek", athlete_id=12345)

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    h.handle(_event(cookie, body={"confirm": "DELETE"}), _FakeContext())
    second = h.handle(_event(cookie, body={"confirm": "DELETE"}), _FakeContext())

    assert second["statusCode"] == 200
    counts = json.loads(second["body"])["deleted"]
    assert counts == {
        "ddb_rows": 0,
        "s3_objects": 0,
        "ssm_user_keys": 0,
        "athlete_map_entries": 0,
        "allowed_emails_entries": 0,
    }


# ─── PK isolation regression ──────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params")
def test_pk_isolation_other_user_data_intact(dynamodb_table: Any, s3_bucket: Any) -> None:
    """Delete tomka NIE rusza DDB/S3/SSM rows weroniki."""
    from handlers.me_delete import handler as h

    _seed_ddb_user(dynamodb_table, "tomek")
    _seed_ddb_user(dynamodb_table, "weronika")
    _seed_s3(s3_bucket, "bodysync-data-test-bucket", "tomek")
    _seed_s3(s3_bucket, "bodysync-data-test-bucket", "weronika")
    ssm = boto3.client("ssm", region_name="eu-west-1")
    _seed_ssm(ssm, "tomek", athlete_id=12345)

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(_event(cookie, body={"confirm": "DELETE"}), _FakeContext())
    assert result["statusCode"] == 200

    # Weronika DDB intact.
    wer_rows = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#weronika"},
    )["Items"]
    assert len(wer_rows) == 3

    # Weronika S3 intact.
    hae_wer = s3_bucket.list_objects_v2(
        Bucket="bodysync-data-test-bucket", Prefix="raw/health-auto-export/weronika/"
    )
    assert hae_wer.get("KeyCount", 0) == 2
    strava_wer = s3_bucket.list_objects_v2(
        Bucket="bodysync-data-test-bucket", Prefix="strava/streams/weronika/"
    )
    assert strava_wer.get("KeyCount", 0) == 1

    # allowed_emails — weronika została.
    allowlist_raw = ssm.get_parameter(Name="/bodysync/auth/allowed_emails")["Parameter"]["Value"]
    assert any(e["user_id"] == "weronika" for e in json.loads(allowlist_raw))
