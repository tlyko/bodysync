"""Tests dla handlers.api_read — GET /api/me + GET /api/biometry."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest


def _event_with_cookie(
    route: str, cookie: str | None, *, query: dict[str, str] | None = None
) -> dict[str, Any]:
    cookies: list[str] = [cookie] if cookie else []
    return {
        "version": "2.0",
        "routeKey": route,
        "headers": {"content-type": "application/json"},
        "cookies": cookies,
        "queryStringParameters": query or {},
        "isBase64Encoded": False,
    }


class _FakeContext:
    aws_request_id = "test-req-id"


def _mint_test_jwt(user_id: str) -> str:
    """Mint JWT używając tego samego sekretu co `ssm_params` fixture."""
    from shared.auth import mint_jwt

    return mint_jwt(user_id)


@pytest.mark.usefixtures("ssm_params")
def test_me_happy(dynamodb_table: Any) -> None:
    from handlers.api_read import handler as h

    # Seed PROFILE row dla tomek
    dynamodb_table.put_item(
        Item={
            "PK": "USER#tomek",
            "SK": "PROFILE",
            "email": "tlyko94@gmail.com",
            "name": "Tomek",
            "last_login": "2026-05-07T12:00:00+00:00",
        }
    )

    token = _mint_test_jwt("tomek")
    cookie = f"bodysync_session={token}"

    result = h.handler(_event_with_cookie("GET /api/me", cookie), _FakeContext())
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body == {"user_id": "tomek", "email": "tlyko94@gmail.com", "name": "Tomek"}


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_me_401_no_cookie() -> None:
    from handlers.api_read import handler as h

    result = h.handler(_event_with_cookie("GET /api/me", cookie=None), _FakeContext())
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_me_401_invalid_jwt() -> None:
    from handlers.api_read import handler as h

    result = h.handler(
        _event_with_cookie("GET /api/me", "bodysync_session=garbage.token.here"), _FakeContext()
    )
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_params")
def test_me_404_profile_not_found(dynamodb_table: Any) -> None:
    """JWT valid (user_id=ghost), ale brak PROFILE row w DDB → 404."""
    from handlers.api_read import handler as h

    token = _mint_test_jwt("ghost")
    result = h.handler(
        _event_with_cookie("GET /api/me", f"bodysync_session={token}"), _FakeContext()
    )
    assert result["statusCode"] == 404


@pytest.mark.usefixtures("ssm_params")
def test_me_pk_isolation(dynamodb_table: Any) -> None:
    """JWT z user_id=tomek nie zwróci PROFILE weroniki."""
    from handlers.api_read import handler as h

    dynamodb_table.put_item(
        Item={
            "PK": "USER#weronika",
            "SK": "PROFILE",
            "email": "weronika.flak@gmail.com",
            "name": "Weronika",
        }
    )
    token = _mint_test_jwt("tomek")
    result = h.handler(
        _event_with_cookie("GET /api/me", f"bodysync_session={token}"), _FakeContext()
    )
    # tomek nie ma PROFILE → 404, w żadnym wypadku nie email weroniki
    assert result["statusCode"] == 404


@pytest.mark.usefixtures("ssm_params")
def test_biometry_happy(dynamodb_table: Any) -> None:
    from handlers.api_read import handler as h

    today = datetime.now(UTC).date().isoformat()
    yesterday = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()

    # Seed kilka rows: 2 dni × kilka metryk
    dynamodb_table.put_item(
        Item={
            "PK": "USER#tomek",
            "SK": f"BIOMETRY#{today}#weight",
            "kg": Decimal("78.4"),
            "source": "apple-health",
        }
    )
    dynamodb_table.put_item(
        Item={
            "PK": "USER#tomek",
            "SK": f"BIOMETRY#{today}#hrv#{today}T07:00:00+00:00",
            "value_ms": Decimal("48.3"),
            "source": "apple-health",
        }
    )
    dynamodb_table.put_item(
        Item={
            "PK": "USER#tomek",
            "SK": f"BIOMETRY#{today}#hrv#{today}T19:00:00+00:00",
            "value_ms": Decimal("52.1"),
            "source": "apple-health",
        }
    )
    dynamodb_table.put_item(
        Item={
            "PK": "USER#tomek",
            "SK": f"BIOMETRY#{yesterday}#weight",
            "kg": Decimal("78.6"),
            "source": "apple-health",
        }
    )

    token = _mint_test_jwt("tomek")
    result = h.handler(
        _event_with_cookie("GET /api/biometry", f"bodysync_session={token}"), _FakeContext()
    )
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert len(body["days"]) == 2

    # Newest first
    assert body["days"][0]["date"] == today
    assert body["days"][1]["date"] == yesterday

    # weight aggregated as single dict, hrv aggregated as list
    today_metrics = body["days"][0]["metrics"]
    assert "weight" in today_metrics
    assert isinstance(today_metrics["weight"], dict)
    assert today_metrics["weight"]["kg"] == 78.4

    assert "hrv" in today_metrics
    assert isinstance(today_metrics["hrv"], list)
    assert len(today_metrics["hrv"]) == 2


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_biometry_empty() -> None:
    """Pusty DDB → 200 + days: []."""
    from handlers.api_read import handler as h

    token = _mint_test_jwt("tomek")
    result = h.handler(
        _event_with_cookie("GET /api/biometry", f"bodysync_session={token}"), _FakeContext()
    )
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body == {"days": []}


@pytest.mark.usefixtures("ssm_params")
def test_biometry_filters_old_days(dynamodb_table: Any) -> None:
    """Row z 30 dni temu nie pojawia się przy days=7 (default)."""
    from handlers.api_read import handler as h

    today = datetime.now(UTC).date()
    old = (today - timedelta(days=30)).isoformat()

    dynamodb_table.put_item(
        Item={"PK": "USER#tomek", "SK": f"BIOMETRY#{old}#weight", "kg": Decimal("80.0")}
    )

    token = _mint_test_jwt("tomek")
    result = h.handler(
        _event_with_cookie("GET /api/biometry", f"bodysync_session={token}"), _FakeContext()
    )
    body = json.loads(result["body"])
    assert body == {"days": []}


@pytest.mark.usefixtures("ssm_params")
def test_biometry_days_query_param(dynamodb_table: Any) -> None:
    """?days=30 znajduje row z 25 dni temu."""
    from handlers.api_read import handler as h

    today = datetime.now(UTC).date()
    older = (today - timedelta(days=25)).isoformat()

    dynamodb_table.put_item(
        Item={"PK": "USER#tomek", "SK": f"BIOMETRY#{older}#weight", "kg": Decimal("80.0")}
    )

    token = _mint_test_jwt("tomek")
    result = h.handler(
        _event_with_cookie("GET /api/biometry", f"bodysync_session={token}", query={"days": "30"}),
        _FakeContext(),
    )
    body = json.loads(result["body"])
    assert len(body["days"]) == 1
    assert body["days"][0]["date"] == older


@pytest.mark.usefixtures("ssm_params")
def test_biometry_pk_isolation(dynamodb_table: Any) -> None:
    """JWT z user_id=tomek NIE widzi BIOMETRY weroniki."""
    from handlers.api_read import handler as h

    today = datetime.now(UTC).date().isoformat()
    dynamodb_table.put_item(
        Item={"PK": "USER#weronika", "SK": f"BIOMETRY#{today}#weight", "kg": Decimal("60.0")}
    )

    token = _mint_test_jwt("tomek")
    result = h.handler(
        _event_with_cookie("GET /api/biometry", f"bodysync_session={token}"), _FakeContext()
    )
    body = json.loads(result["body"])
    assert body == {"days": []}


@pytest.mark.usefixtures("ssm_params")
def test_biometry_cumulative_aggregated_to_sum(dynamodb_table: Any) -> None:
    """Cumulative metrics (steps, kcal_in, etc.) — multi-point hourly buckets
    z PR #46 sumują się do single dict z `samples` count, nie listy."""
    from handlers.api_read import handler as h

    today = datetime.now(UTC).date().isoformat()
    # 3 hourly buckety dla kcal_in
    for hour, qty in [("09:00", "300.5"), ("13:00", "550.25"), ("19:00", "420.10")]:
        dynamodb_table.put_item(
            Item={
                "PK": "USER#tomek",
                "SK": f"BIOMETRY#{today}#kcal_in#{today}T{hour}:00+02:00",
                "kcal": Decimal(qty),
                "device": "Fitatu",
                "source": "apple-health",
            }
        )

    token = _mint_test_jwt("tomek")
    result = h.handler(
        _event_with_cookie("GET /api/biometry", f"bodysync_session={token}"), _FakeContext()
    )
    body = json.loads(result["body"])
    today_metrics = body["days"][0]["metrics"]

    assert "kcal_in" in today_metrics
    kcal = today_metrics["kcal_in"]
    assert isinstance(kcal, dict)
    assert abs(float(kcal["kcal"]) - 1270.85) < 0.01
    assert kcal["samples"] == 3
    assert kcal["device"] == "Fitatu"


@pytest.mark.usefixtures("ssm_params")
def test_biometry_cumulative_legacy_single_point_still_aggregated(
    dynamodb_table: Any,
) -> None:
    """Defense in depth: legacy single-point cumulative SK (pre-PR-#46) też
    przechodzi przez aggregation — bez crash, samples=1.
    """
    from handlers.api_read import handler as h

    today = datetime.now(UTC).date().isoformat()
    dynamodb_table.put_item(
        Item={
            "PK": "USER#tomek",
            "SK": f"BIOMETRY#{today}#steps",  # legacy 3-part SK
            "count": Decimal("8500"),
            "device": "iPhone",
            "source": "apple-health",
        }
    )

    token = _mint_test_jwt("tomek")
    result = h.handler(
        _event_with_cookie("GET /api/biometry", f"bodysync_session={token}"), _FakeContext()
    )
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    steps = body["days"][0]["metrics"]["steps"]
    assert steps["count"] == 8500
    assert steps["samples"] == 1


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_unknown_route_404() -> None:
    from handlers.api_read import handler as h

    token = _mint_test_jwt("tomek")
    result = h.handler(
        _event_with_cookie("GET /api/something-else", f"bodysync_session={token}"), _FakeContext()
    )
    assert result["statusCode"] == 404
