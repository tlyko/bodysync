"""Tests dla GET /api/strava/oauth/callback."""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import boto3
import httpx
import pytest


def _event(qs: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "version": "2.0",
        "routeKey": "GET /api/strava/oauth/callback",
        "rawPath": "/api/strava/oauth/callback",
        "requestContext": {"http": {"method": "GET"}},
        "headers": {},
        "cookies": [],
        "queryStringParameters": qs or {},
        "isBase64Encoded": False,
    }


class _FakeContext:
    aws_request_id = "test-req-id"


@pytest.fixture
def strava_ssm(ssm_params: None) -> None:
    """Pre-seed Strava SSM params (client_id, client_secret, athlete-to-user empty)."""
    client = boto3.client("ssm", region_name="eu-west-1")
    client.put_parameter(
        Name="/bodysync/strava/client_id",
        Value="123456",
        Type="String",
    )
    client.put_parameter(
        Name="/bodysync/strava/client_secret",
        Value="0123456789abcdef0123456789abcdef01234567",  # >32 chars
        Type="SecureString",
    )
    client.put_parameter(
        Name="/bodysync/strava/athlete-to-user",
        Value="{}",
        Type="String",
    )
    from shared import ssm as _ssm

    _ssm.clear_cache()


def _seed_state(table: Any, state: str, user_id: str, ttl_offset: int = 600) -> None:
    table.put_item(
        Item={
            "PK": f"STRAVA_OAUTH_STATE#{state}",
            "SK": "META",
            "user_id": user_id,
            "ttl": int(time.time()) + ttl_offset,
        }
    )


def _redirect_status(result: dict[str, Any]) -> str:
    """Wyciąga `?strava=<status>` z Location header."""
    parsed = urlparse(result["headers"]["Location"])
    qs = parse_qs(parsed.query)
    return qs["strava"][0]


# ─── Error paths (no token exchange) ──────────────────────────────────────


@pytest.mark.usefixtures("strava_ssm", "dynamodb_table")
def test_user_denied_redirects_with_denied_status() -> None:
    from handlers.strava_oauth_callback import handler as h

    result = h.handler(_event({"error": "access_denied"}), _FakeContext())
    assert result["statusCode"] == 302
    assert _redirect_status(result) == "denied"


@pytest.mark.usefixtures("strava_ssm", "dynamodb_table")
def test_missing_code_or_state_redirects_with_missing_params() -> None:
    from handlers.strava_oauth_callback import handler as h

    result = h.handler(_event({"code": "abc"}), _FakeContext())  # no state
    assert _redirect_status(result) == "missing_params"


@pytest.mark.usefixtures("strava_ssm", "dynamodb_table")
def test_unknown_state_redirects_with_invalid_state() -> None:
    from handlers.strava_oauth_callback import handler as h

    result = h.handler(_event({"code": "abc", "state": "never-minted"}), _FakeContext())
    assert _redirect_status(result) == "invalid_state"


@pytest.mark.usefixtures("strava_ssm")
def test_expired_state_redirects_with_expired_state(dynamodb_table: Any) -> None:
    from handlers.strava_oauth_callback import handler as h

    _seed_state(dynamodb_table, "expired-state", "tomek", ttl_offset=-60)
    result = h.handler(_event({"code": "abc", "state": "expired-state"}), _FakeContext())
    assert _redirect_status(result) == "expired_state"


@pytest.mark.usefixtures("strava_ssm")
def test_state_used_twice_second_call_invalid_state(dynamodb_table: Any) -> None:
    """Atomic delete — drugi callback z tym samym state → invalid."""
    from handlers.strava_oauth_callback import handler as h

    _seed_state(dynamodb_table, "single-use", "tomek")
    happy_response = httpx.Response(
        200,
        json={
            "access_token": "a",
            "refresh_token": "r",
            "expires_at": int(time.time()) + 21600,
            "athlete": {"id": 999},
        },
    )
    with patch(
        "handlers.strava_oauth_callback.service.httpx.Client.post",
        return_value=happy_response,
    ):
        first = h.handler(_event({"code": "abc", "state": "single-use"}), _FakeContext())
        assert _redirect_status(first) == "ok"

    second = h.handler(_event({"code": "abc", "state": "single-use"}), _FakeContext())
    assert _redirect_status(second) == "invalid_state"


# ─── Token exchange happy path ────────────────────────────────────────────


@pytest.mark.usefixtures("strava_ssm")
def test_happy_path_persists_tokens_and_updates_athlete_map(
    dynamodb_table: Any,
) -> None:
    from handlers.strava_oauth_callback import handler as h

    _seed_state(dynamodb_table, "good-state", "tomek")
    happy = httpx.Response(
        200,
        json={
            "access_token": "AT_TOMEK",
            "refresh_token": "RT_TOMEK",
            "expires_at": int(time.time()) + 21600,
            "athlete": {"id": 12345, "firstname": "Tomek"},
        },
    )
    with patch("handlers.strava_oauth_callback.service.httpx.Client.post", return_value=happy):
        result = h.handler(_event({"code": "valid-code", "state": "good-state"}), _FakeContext())
    assert _redirect_status(result) == "ok"

    # Tokens persisted
    ssm = boto3.client("ssm", region_name="eu-west-1")
    raw = ssm.get_parameter(Name="/bodysync/strava/tomek/tokens", WithDecryption=True)["Parameter"][
        "Value"
    ]
    tokens = json.loads(raw)
    assert tokens["access_token"] == "AT_TOMEK"
    assert tokens["refresh_token"] == "RT_TOMEK"
    assert tokens["athlete_id"] == 12345

    # Athlete map updated
    map_raw = ssm.get_parameter(Name="/bodysync/strava/athlete-to-user")["Parameter"]["Value"]
    assert json.loads(map_raw) == {"12345": "tomek"}


@pytest.mark.usefixtures("strava_ssm")
def test_happy_path_does_not_log_token_or_code(
    dynamodb_table: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Audit guard — żaden log record nie zawiera token/code value."""
    from handlers.strava_oauth_callback import handler as h

    _seed_state(dynamodb_table, "log-test", "tomek")
    happy = httpx.Response(
        200,
        json={
            "access_token": "SECRET_TOKEN_VALUE",
            "refresh_token": "SECRET_REFRESH_VALUE",
            "expires_at": int(time.time()) + 21600,
            "athlete": {"id": 1},
        },
    )
    with (
        caplog.at_level(logging.DEBUG, logger="strava_oauth_callback"),
        patch(
            "handlers.strava_oauth_callback.service.httpx.Client.post",
            return_value=happy,
        ),
    ):
        h.handler(
            _event({"code": "MY_AUTH_CODE", "state": "log-test"}),
            _FakeContext(),
        )

    full_log_text = (
        " ".join(r.getMessage() for r in caplog.records)
        + " "
        + " ".join(str(getattr(r, k, "")) for r in caplog.records for k in vars(r))
    )
    assert "SECRET_TOKEN_VALUE" not in full_log_text
    assert "SECRET_REFRESH_VALUE" not in full_log_text
    assert "MY_AUTH_CODE" not in full_log_text


@pytest.mark.usefixtures("strava_ssm")
def test_pk_isolation_two_users_separate_tokens(dynamodb_table: Any) -> None:
    """Różni userzy OAuth → osobne SSM paths, athlete-to-user ma 2 entries."""
    from handlers.strava_oauth_callback import handler as h

    _seed_state(dynamodb_table, "tomek-state", "tomek")
    _seed_state(dynamodb_table, "weronika-state", "weronika")

    def fake_post_factory(athlete_id: int, access: str):
        return httpx.Response(
            200,
            json={
                "access_token": access,
                "refresh_token": f"RT_{athlete_id}",
                "expires_at": int(time.time()) + 21600,
                "athlete": {"id": athlete_id},
            },
        )

    with patch(
        "handlers.strava_oauth_callback.service.httpx.Client.post",
        return_value=fake_post_factory(11111, "AT_TOMEK"),
    ):
        h.handler(_event({"code": "c1", "state": "tomek-state"}), _FakeContext())
    with patch(
        "handlers.strava_oauth_callback.service.httpx.Client.post",
        return_value=fake_post_factory(22222, "AT_WERONIKA"),
    ):
        h.handler(_event({"code": "c2", "state": "weronika-state"}), _FakeContext())

    ssm = boto3.client("ssm", region_name="eu-west-1")
    tomek = json.loads(
        ssm.get_parameter(Name="/bodysync/strava/tomek/tokens", WithDecryption=True)["Parameter"][
            "Value"
        ]
    )
    weronika = json.loads(
        ssm.get_parameter(Name="/bodysync/strava/weronika/tokens", WithDecryption=True)[
            "Parameter"
        ]["Value"]
    )
    assert tomek["athlete_id"] == 11111
    assert weronika["athlete_id"] == 22222

    map_data = json.loads(
        ssm.get_parameter(Name="/bodysync/strava/athlete-to-user")["Parameter"]["Value"]
    )
    assert map_data == {"11111": "tomek", "22222": "weronika"}


# ─── Token exchange errors ────────────────────────────────────────────────


@pytest.mark.usefixtures("strava_ssm")
def test_strava_400_redirects_with_token_exchange_failed(
    dynamodb_table: Any,
) -> None:
    from handlers.strava_oauth_callback import handler as h

    _seed_state(dynamodb_table, "bad-code-state", "tomek")
    rejected = httpx.Response(
        400, json={"message": "Bad Request", "errors": [{"resource": "code"}]}
    )
    with patch(
        "handlers.strava_oauth_callback.service.httpx.Client.post",
        return_value=rejected,
    ):
        result = h.handler(_event({"code": "expired", "state": "bad-code-state"}), _FakeContext())
    assert _redirect_status(result) == "token_exchange_failed"


@pytest.mark.usefixtures("strava_ssm")
def test_network_error_redirects_with_token_exchange_failed(
    dynamodb_table: Any,
) -> None:
    from handlers.strava_oauth_callback import handler as h

    _seed_state(dynamodb_table, "net-state", "tomek")
    with patch(
        "handlers.strava_oauth_callback.service.httpx.Client.post",
        side_effect=httpx.ConnectError("connection refused"),
    ):
        result = h.handler(_event({"code": "abc", "state": "net-state"}), _FakeContext())
    assert _redirect_status(result) == "token_exchange_failed"
