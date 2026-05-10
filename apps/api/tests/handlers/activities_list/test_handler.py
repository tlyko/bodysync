"""Tests dla GET /api/activities."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest


def _event(cookie: str | None, qs: dict[str, str] | None = None) -> dict[str, Any]:
    cookies: list[str] = [cookie] if cookie else []
    return {
        "version": "2.0",
        "routeKey": "GET /api/activities",
        "rawPath": "/api/activities",
        "requestContext": {"http": {"method": "GET"}},
        "headers": {},
        "cookies": cookies,
        "queryStringParameters": qs or {},
        "isBase64Encoded": False,
    }


class _Ctx:
    aws_request_id = "test-req-id"


def _mint_jwt(user_id: str) -> str:
    from shared.auth import mint_jwt

    return mint_jwt(user_id)


def _seed_activity(
    table: Any,
    user_id: str,
    strava_id: int,
    *,
    sport_type: str = "Run",
    start_date: str = "2026-05-08T06:30:00Z",
    distance_m: float = 5000.0,
    summary_polyline: str | None = None,
) -> None:
    item: dict[str, Any] = {
        "PK": f"USER#{user_id}",
        "SK": f"ACTIVITY#{strava_id}",
        "strava_id": strava_id,
        "name": f"Activity {strava_id}",
        "sport_type": sport_type,
        "type": sport_type,
        "distance_m": Decimal(str(distance_m)),
        "moving_time_s": 1800,
        "elapsed_time_s": 1900,
        "elevation_gain_m": Decimal("10.5"),
        "start_date": start_date,
        "start_date_local": start_date.replace("Z", ""),
        "timezone": "Europe/Warsaw",
    }
    if summary_polyline is not None:
        item["summary_polyline"] = summary_polyline
    table.put_item(Item=item)


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_activities_401_no_cookie() -> None:
    from handlers.activities_list import handler as h

    result = h.handler(_event(cookie=None), _Ctx())
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_activities_401_invalid_jwt() -> None:
    from handlers.activities_list import handler as h

    result = h.handler(_event("bodysync_session=garbage"), _Ctx())
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_params")
def test_activities_returns_user_activities_descending_by_start_date(
    dynamodb_table: Any,
) -> None:
    from handlers.activities_list import handler as h

    _seed_activity(dynamodb_table, "tomek", 1, start_date="2026-05-01T06:00:00Z")
    _seed_activity(dynamodb_table, "tomek", 2, start_date="2026-05-08T06:00:00Z")
    _seed_activity(dynamodb_table, "tomek", 3, start_date="2026-05-05T06:00:00Z")

    cookie = f"bodysync_session={_mint_jwt('tomek')}"
    result = h.handler(_event(cookie), _Ctx())
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    items = body["items"]
    assert [i["strava_id"] for i in items] == [2, 3, 1]


@pytest.mark.usefixtures("ssm_params")
def test_activities_pk_isolation_two_users(dynamodb_table: Any) -> None:
    from handlers.activities_list import handler as h

    _seed_activity(dynamodb_table, "tomek", 100)
    _seed_activity(dynamodb_table, "weronika", 200)

    tomek_cookie = f"bodysync_session={_mint_jwt('tomek')}"
    result = h.handler(_event(tomek_cookie), _Ctx())
    body = json.loads(result["body"])
    assert [i["strava_id"] for i in body["items"]] == [100]


@pytest.mark.usefixtures("ssm_params")
def test_activities_limit_clamped(dynamodb_table: Any) -> None:
    from handlers.activities_list import handler as h

    for i in range(15):
        _seed_activity(
            dynamodb_table,
            "tomek",
            i,
            start_date=f"2026-05-{str(i + 1).zfill(2)}T06:00:00Z",
        )

    cookie = f"bodysync_session={_mint_jwt('tomek')}"

    # Default limit = 10
    result = h.handler(_event(cookie), _Ctx())
    body = json.loads(result["body"])
    assert len(body["items"]) == 10

    # Custom limit = 5
    result = h.handler(_event(cookie, qs={"limit": "5"}), _Ctx())
    body = json.loads(result["body"])
    assert len(body["items"]) == 5

    # Limit > MAX_LIMIT (50) → clamped
    result = h.handler(_event(cookie, qs={"limit": "1000"}), _Ctx())
    body = json.loads(result["body"])
    assert len(body["items"]) <= 50


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_activities_empty_user_returns_empty_list() -> None:
    from handlers.activities_list import handler as h

    cookie = f"bodysync_session={_mint_jwt('newuser')}"
    result = h.handler(_event(cookie), _Ctx())
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body == {"items": []}


@pytest.mark.usefixtures("ssm_params")
def test_activities_decimal_serialized_as_number(dynamodb_table: Any) -> None:
    """boto3 zwraca Decimal dla N attributes — JSON dump musi je zamienić."""
    from handlers.activities_list import handler as h

    _seed_activity(dynamodb_table, "tomek", 1, distance_m=5234.5)

    cookie = f"bodysync_session={_mint_jwt('tomek')}"
    result = h.handler(_event(cookie), _Ctx())
    body = json.loads(result["body"])
    assert body["items"][0]["distance_m"] == 5234.5
    assert isinstance(body["items"][0]["moving_time_s"], int)


@pytest.mark.usefixtures("ssm_params")
def test_activities_returns_polyline_when_persisted(dynamodb_table: Any) -> None:
    """Sprint 10 A9 — summary_polyline w response gdy obecny w DDB row."""
    from handlers.activities_list import handler as h

    _seed_activity(
        dynamodb_table, "tomek", 1, summary_polyline="u_p~Fvfbb@aBpHaCnSmDl["
    )
    _seed_activity(dynamodb_table, "tomek", 2)  # bez polyline (pre-A9 row)

    cookie = f"bodysync_session={_mint_jwt('tomek')}"
    result = h.handler(_event(cookie), _Ctx())
    body = json.loads(result["body"])

    items_by_id = {item["strava_id"]: item for item in body["items"]}
    assert items_by_id[1]["summary_polyline"] == "u_p~Fvfbb@aBpHaCnSmDl["
    # No-GPS / pre-A9: zwracamy null (NIE klucz brak)
    assert items_by_id[2]["summary_polyline"] is None
