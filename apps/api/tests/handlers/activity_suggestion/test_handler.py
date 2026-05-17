"""Tests dla handlers.activity_suggestion (Sprint 10 A0.5).

Coverage:
- happy: 7d data → LLM zwraca level + reasoning, response 200
- pre-pre prompt context build: activities count + steps avg w response
- empty data: 0 activities + 0 biometry → LLM zwraca sedentary
- malformed JSON output → 502
- invalid level (LLM hallucinates) → 502 (Pydantic literal violation)
- Anthropic key PLACEHOLDER → 503
- 401 no JWT cookie
- PK isolation: user_b activities NIE leakują do user_a context
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

WARSAW_TZ = ZoneInfo("Europe/Warsaw")


_CSRF_TEST_TOKEN = "test-csrf-token-deterministic"


def _event(cookie: str | None, *, csrf: bool = True) -> dict[str, Any]:
    cookies: list[str] = [cookie] if cookie else []
    headers: dict[str, str] = {"content-type": "application/json"}
    if csrf:
        cookies.append(f"bodysync_csrf={_CSRF_TEST_TOKEN}")
        headers["x-csrf-token"] = _CSRF_TEST_TOKEN
    return {
        "version": "2.0",
        "routeKey": "POST /api/profile/suggest-activity-level",
        "rawPath": "/api/profile/suggest-activity-level",
        "requestContext": {"http": {"method": "POST"}},
        "headers": headers,
        "cookies": cookies,
        "body": "{}",
        "isBase64Encoded": False,
    }


class _FakeContext:
    aws_request_id = "test-req-id"


def _mint_test_jwt(user_id: str) -> str:
    from shared.auth import mint_jwt

    return mint_jwt(user_id)


def _seed_activity(
    table: Any,
    user_id: str,
    *,
    strava_id: int,
    sport_type: str,
    distance_m: float,
    moving_time_s: float,
    days_ago: int,
) -> None:
    """Insert ACTIVITY row z start_date = today - days_ago."""
    today = datetime.now(WARSAW_TZ).date()
    start = (today - timedelta(days=days_ago)).isoformat() + "T10:00:00Z"
    table.put_item(
        Item={
            "PK": f"USER#{user_id}",
            "SK": f"ACTIVITY#{strava_id}",
            "strava_id": strava_id,
            "sport_type": sport_type,
            "distance_m": Decimal(str(distance_m)),
            "moving_time_s": Decimal(str(moving_time_s)),
            "start_date": start,
        }
    )


def _seed_biometry_steps(table: Any, user_id: str, *, days_ago: int, count: int) -> None:
    today = datetime.now(WARSAW_TZ).date()
    d = (today - timedelta(days=days_ago)).isoformat()
    table.put_item(
        Item={
            "PK": f"USER#{user_id}",
            "SK": f"BIOMETRY#{d}#steps#{int(time.time()) + days_ago}",
            "count": Decimal(str(count)),
        }
    )


def _seed_biometry_kcal_active(table: Any, user_id: str, *, days_ago: int, kcal: float) -> None:
    today = datetime.now(WARSAW_TZ).date()
    d = (today - timedelta(days=days_ago)).isoformat()
    table.put_item(
        Item={
            "PK": f"USER#{user_id}",
            "SK": f"BIOMETRY#{d}#kcal_active#{int(time.time()) + days_ago}",
            "kcal": Decimal(str(kcal)),
        }
    )


# ─── happy path ───────────────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_with_anthropic_key", "patched_anthropic_client", "dynamodb_table")
def test_without_csrf_returns_403() -> None:
    """POST bez CSRF token → 403 (sec audit 2026-05-16 P1-4)."""
    from handlers.activity_suggestion import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_event(cookie, csrf=False), _FakeContext())
    assert result["statusCode"] == 403


@pytest.mark.usefixtures("ssm_with_anthropic_key", "patched_anthropic_client")
def test_happy_returns_level_and_reasoning_with_summary(
    dynamodb_table: Any, patched_anthropic_client: MagicMock
) -> None:
    from handlers.activity_suggestion import handler as h

    # Seed 4 activities + 7d steps + 7d kcal_active
    _seed_activity(
        dynamodb_table,
        "tomek",
        strava_id=1,
        sport_type="Run",
        distance_m=10000,
        moving_time_s=3000,
        days_ago=1,
    )
    _seed_activity(
        dynamodb_table,
        "tomek",
        strava_id=2,
        sport_type="Run",
        distance_m=8000,
        moving_time_s=2400,
        days_ago=3,
    )
    _seed_activity(
        dynamodb_table,
        "tomek",
        strava_id=3,
        sport_type="Run",
        distance_m=12000,
        moving_time_s=3600,
        days_ago=5,
    )
    _seed_activity(
        dynamodb_table,
        "tomek",
        strava_id=4,
        sport_type="Ride",
        distance_m=35000,
        moving_time_s=5400,
        days_ago=2,
    )
    for d in range(7):
        _seed_biometry_steps(dynamodb_table, "tomek", days_ago=d, count=8000 + d * 100)
        _seed_biometry_kcal_active(dynamodb_table, "tomek", days_ago=d, kcal=550 + d * 20)

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_event(cookie), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["level"] == "moderate"
    assert (
        "moderate" in body["reasoning"].lower()
        or "8200" in body["reasoning"]
        or len(body["reasoning"]) > 5
    )
    assert body["activities_count"] == 4
    assert body["avg_steps"] is not None
    assert 8000 <= body["avg_steps"] <= 8800
    assert body["avg_kcal_active"] is not None

    # Verify LLM call shape — system prompt cached, user message ma activity_context
    call = patched_anthropic_client.messages.create.call_args
    assert call.kwargs["model"] == "claude-haiku-4-5-20251001"
    assert call.kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    user_msg = call.kwargs["messages"][0]["content"]
    assert "<activity_context>" in user_msg
    assert "Run: 3×" in user_msg
    assert "Ride: 1×" in user_msg


@pytest.mark.usefixtures("ssm_with_anthropic_key", "patched_anthropic_client")
def test_empty_data_passes_no_activities_to_llm(
    dynamodb_table: Any, patched_anthropic_client: MagicMock, anthropic_json_factory: Any
) -> None:
    from handlers.activity_suggestion import handler as h

    # No seed — pusty user
    patched_anthropic_client.messages.create.return_value = anthropic_json_factory(
        json_text='{"level": "sedentary", "reasoning": "Brak wystarczających danych w ostatnich 7 dniach."}'
    )

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_event(cookie), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["level"] == "sedentary"
    assert body["activities_count"] == 0
    assert body["avg_steps"] is None
    assert body["avg_kcal_active"] is None

    # Context block musi mieć "(brak)" + "Brak danych"
    user_msg = patched_anthropic_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "(brak)" in user_msg
    assert "Brak danych" in user_msg


# ─── error paths ──────────────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_with_anthropic_key", "patched_anthropic_client")
def test_malformed_json_output_returns_502(
    dynamodb_table: Any, patched_anthropic_client: MagicMock, anthropic_json_factory: Any
) -> None:
    from handlers.activity_suggestion import handler as h

    patched_anthropic_client.messages.create.return_value = anthropic_json_factory(
        json_text="To nie jest JSON, tylko prose response."
    )

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_event(cookie), _FakeContext())

    assert result["statusCode"] == 502
    body = json.loads(result["body"])
    assert body["error"] == "advisor_backend_error"
    assert body["reason"] == "json_parse_failed"


@pytest.mark.usefixtures("ssm_with_anthropic_key", "patched_anthropic_client")
def test_invalid_level_in_llm_output_returns_502(
    dynamodb_table: Any, patched_anthropic_client: MagicMock, anthropic_json_factory: Any
) -> None:
    """LLM hallucinates `level: "extreme"` (poza Literal) → Pydantic validation
    fails, handler 502 z `schema_validation_failed` reason."""
    from handlers.activity_suggestion import handler as h

    patched_anthropic_client.messages.create.return_value = anthropic_json_factory(
        json_text='{"level": "extreme", "reasoning": "Halucynacja LLM."}'
    )

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_event(cookie), _FakeContext())

    assert result["statusCode"] == 502
    body = json.loads(result["body"])
    assert body["reason"] == "schema_validation_failed"


@pytest.mark.usefixtures("ssm_with_anthropic_key", "patched_anthropic_client")
def test_llm_wraps_json_in_markdown_fence_still_parses(
    dynamodb_table: Any, patched_anthropic_client: MagicMock, anthropic_json_factory: Any
) -> None:
    """LLM occasionally wraps w ```json ... ``` markdown fence — `_extract_json`
    powinien wyciągnąć inner block."""
    from handlers.activity_suggestion import handler as h

    patched_anthropic_client.messages.create.return_value = anthropic_json_factory(
        json_text='Oto wynik:\n```json\n{"level": "light", "reasoning": "Mało treningów."}\n```\nKoniec.'
    )

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_event(cookie), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["level"] == "light"


def test_anthropic_placeholder_returns_503(ssm_params: None, dynamodb_table: Any) -> None:
    """SSM Anthropic key = PLACEHOLDER → handler 503 (no LLM call attempt)."""
    import boto3

    client = boto3.client("ssm", region_name="eu-west-1")
    client.put_parameter(
        Name="/bodysync/anthropic/api_key",
        Value="PLACEHOLDER",
        Type="SecureString",
        Overwrite=True,
    )
    from shared import ssm as _ssm

    _ssm.clear_cache()

    from handlers.activity_suggestion import handler as h
    from handlers.activity_suggestion import service

    service._reset_client_for_tests()

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_event(cookie), _FakeContext())

    assert result["statusCode"] == 503
    body = json.loads(result["body"])
    assert body["error"] == "advisor_unavailable"


# ─── auth / PK isolation ───────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_with_anthropic_key", "patched_anthropic_client", "dynamodb_table")
def test_no_cookie_returns_401() -> None:
    from handlers.activity_suggestion import handler as h

    result = h.handler(_event(cookie=None), _FakeContext())
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_with_anthropic_key", "patched_anthropic_client")
def test_pk_isolation_user_a_activities_not_in_user_b_context(
    dynamodb_table: Any, patched_anthropic_client: MagicMock
) -> None:
    """Critical PK invariant — user_a ma 5 activities, user_b 0. user_b
    request NIE może widzieć user_a Strava history w LLM context."""
    from handlers.activity_suggestion import handler as h

    for i in range(5):
        _seed_activity(
            dynamodb_table,
            "user_a",
            strava_id=100 + i,
            sport_type="Run",
            distance_m=10000,
            moving_time_s=3000,
            days_ago=i,
        )

    cookie = f"bodysync_session={_mint_test_jwt('user_b')}"
    result = h.handler(_event(cookie), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["activities_count"] == 0  # NIE leak user_a 5 activities

    # Context block dla user_b NIE może mieć "Run: 5×"
    user_msg = patched_anthropic_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Run:" not in user_msg
    assert "(brak)" in user_msg
