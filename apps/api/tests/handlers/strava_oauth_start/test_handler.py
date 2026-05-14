"""Tests dla GET /api/strava/oauth/start."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import boto3
import pytest


def _event(cookie: str | None) -> dict[str, Any]:
    cookies: list[str] = [cookie] if cookie else []
    return {
        "version": "2.0",
        "routeKey": "GET /api/strava/oauth/start",
        "rawPath": "/api/strava/oauth/start",
        "requestContext": {"http": {"method": "GET"}},
        "headers": {},
        "cookies": cookies,
        "queryStringParameters": {},
        "isBase64Encoded": False,
    }


class _FakeContext:
    aws_request_id = "test-req-id"


def _mint_test_jwt(user_id: str) -> str:
    from shared.auth import mint_jwt

    return mint_jwt(user_id)


@pytest.fixture
def strava_client_id_ssm(ssm_params: None) -> None:
    """Pre-seed SSM client_id z testową wartością."""
    boto3.client("ssm", region_name="eu-west-1").put_parameter(
        Name="/bodysync/strava/client_id",
        Value="123456",
        Type="String",
    )
    from shared import ssm as _ssm

    _ssm.clear_cache()


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_oauth_start_unauthenticated_returns_401() -> None:
    from handlers.strava_oauth_start import handler as h

    result = h.handler(_event(cookie=None), _FakeContext())
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_oauth_start_invalid_jwt_returns_401() -> None:
    from handlers.strava_oauth_start import handler as h

    result = h.handler(_event("bodysync_session=garbage.token.here"), _FakeContext())
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("strava_client_id_ssm", "dynamodb_table")
def test_oauth_start_returns_302_with_strava_authorize_url() -> None:
    from handlers.strava_oauth_start import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_event(cookie), _FakeContext())

    assert result["statusCode"] == 302
    location = result["headers"]["Location"]
    parsed = urlparse(location)
    assert parsed.scheme == "https"
    assert parsed.netloc == "www.strava.com"
    assert parsed.path == "/oauth/mobile/authorize"

    qs = parse_qs(parsed.query)
    assert qs["client_id"] == ["123456"]
    assert qs["redirect_uri"] == ["https://api.bodysync.pl/api/strava/oauth/callback"]
    assert qs["response_type"] == ["code"]
    assert qs["scope"] == ["read,activity:read_all"]
    assert "state" in qs
    assert len(qs["state"][0]) >= 32  # token_urlsafe(32) → ~43 chars


@pytest.mark.usefixtures("strava_client_id_ssm")
def test_oauth_start_creates_ddb_state_row_with_user_id(dynamodb_table: Any) -> None:
    from handlers.strava_oauth_start import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('weronika')}"
    before = int(time.time())
    result = h.handler(_event(cookie), _FakeContext())
    after = int(time.time())

    assert result["statusCode"] == 302

    # Wyciągnij state z URL
    qs = parse_qs(urlparse(result["headers"]["Location"]).query)
    state = qs["state"][0]

    # DDB row istnieje pod PK=STRAVA_OAUTH_STATE#{state}, SK=META
    row = dynamodb_table.get_item(Key={"PK": f"STRAVA_OAUTH_STATE#{state}", "SK": "META"})["Item"]
    assert row["user_id"] == "weronika"
    # TTL ~ now + 600 (10 min); allow ±5s window dla test execution
    assert before + 600 - 5 <= int(row["ttl"]) <= after + 600 + 5


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_oauth_start_503_when_client_id_placeholder() -> None:
    """Owner nie wpisał real client_id — handler fail loud z 503."""
    boto3.client("ssm", region_name="eu-west-1").put_parameter(
        Name="/bodysync/strava/client_id",
        Value="PLACEHOLDER",
        Type="String",
    )
    from shared import ssm as _ssm

    _ssm.clear_cache()
    from handlers.strava_oauth_start import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_event(cookie), _FakeContext())
    assert result["statusCode"] == 503


@pytest.mark.usefixtures("strava_client_id_ssm")
def test_oauth_start_each_call_generates_unique_state(dynamodb_table: Any) -> None:
    from handlers.strava_oauth_start import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    states: set[str] = set()
    for _ in range(5):
        result = h.handler(_event(cookie), _FakeContext())
        qs = parse_qs(urlparse(result["headers"]["Location"]).query)
        states.add(qs["state"][0])
    assert len(states) == 5  # collision-free
