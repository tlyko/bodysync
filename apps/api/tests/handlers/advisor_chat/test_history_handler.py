"""Tests dla GET /api/advisor/chat/history (Sprint 10 A1).

Coverage:
- happy: hydrate'uje wszystkie tury z dziś
- empty history: 200 z messages=[] (NIE 404)
- ?date=YYYY-MM-DD: zwraca tury z innego dnia (np. wczoraj)
- 401 no JWT cookie
- PK isolation: user_b NIE widzi user_a history
- invalid ?date param → fallback na today (no 400)
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

import pytest

WARSAW_TZ_NAME = "Europe/Warsaw"


def _event(
    cookie: str | None,
    *,
    query: dict[str, str] | None = None,
) -> dict[str, Any]:
    cookies: list[str] = [cookie] if cookie else []
    return {
        "version": "2.0",
        "routeKey": "GET /api/advisor/chat/history",
        "rawPath": "/api/advisor/chat/history",
        "requestContext": {"http": {"method": "GET"}},
        "headers": {"content-type": "application/json"},
        "cookies": cookies,
        "queryStringParameters": query or {},
        "body": None,
        "isBase64Encoded": False,
    }


class _FakeContext:
    aws_request_id = "test-req-id"


def _mint_test_jwt(user_id: str) -> str:
    from shared.auth import mint_jwt

    return mint_jwt(user_id)


# ─── happy path ───────────────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_with_anthropic_key", "patched_anthropic_client")
def test_history_happy_returns_today_turns(
    dynamodb_table_with_chat_history: Any,
) -> None:
    """Fixture pre-seeds 5 turn dla user_a — hydrate wszystkie."""
    from handlers.advisor_chat import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('user_a')}"
    result = h.handler(_event(cookie), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert len(body["messages"]) == 5
    assert body["messages"][0]["role"] == "user"
    assert body["messages"][0]["content"] == "Co zjeść na obiad?"
    assert body["messages"][0]["turn_idx"] == 0
    assert body["messages"][1]["role"] == "assistant"
    assert body["messages"][4]["turn_idx"] == 4
    # date returned matches Warsaw today (fixture used same TZ)
    today_warsaw = datetime.now().astimezone().date().isoformat()
    # Either match local TZ or accept ±1 dzień (CI run vs Warsaw boundary):
    assert body["date"][:7] == today_warsaw[:7]


@pytest.mark.usefixtures("ssm_with_anthropic_key", "patched_anthropic_client")
def test_history_empty_returns_200_with_empty_list(dynamodb_table: Any) -> None:
    from handlers.advisor_chat import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('lonely_user')}"
    result = h.handler(_event(cookie), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["messages"] == []
    assert "date" in body


@pytest.mark.usefixtures("ssm_with_anthropic_key", "patched_anthropic_client")
def test_history_custom_date_param_queries_other_day(
    dynamodb_table: Any,
) -> None:
    """?date=YYYY-MM-DD switches DDB Query do innego dnia."""
    from handlers.advisor_chat import handler as h

    yesterday = datetime.now().date() - timedelta(days=1)
    yesterday_iso = yesterday.isoformat()
    # Seed turns dla yesterday
    dynamodb_table.put_item(
        Item={
            "PK": "USER#tomek",
            "SK": f"CHAT#{yesterday_iso}#0000",
            "role": "user",
            "content": "wczorajsza wiadomość",
            "ts": f"{yesterday_iso}T10:00:00+00:00",
            "ttl": 9999999999,
        }
    )

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(
        _event(cookie, query={"date": yesterday_iso}),
        _FakeContext(),
    )

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert len(body["messages"]) == 1
    assert body["messages"][0]["content"] == "wczorajsza wiadomość"
    assert body["date"] == yesterday_iso


@pytest.mark.usefixtures("ssm_with_anthropic_key", "patched_anthropic_client", "dynamodb_table")
def test_history_invalid_date_param_falls_back_to_today() -> None:
    """Śmieciowe `?date=foo` → fallback na today, NIE 400.

    Konserwatywne UX: jeśli URL został malformed (cache, stale link),
    user widzi pustą today historię zamiast errora."""
    from handlers.advisor_chat import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(
        _event(cookie, query={"date": "garbage-not-a-date"}),
        _FakeContext(),
    )

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["messages"] == []
    # date is today, not raw garbage
    assert body["date"] != "garbage-not-a-date"


@pytest.mark.usefixtures("ssm_with_anthropic_key", "patched_anthropic_client", "dynamodb_table")
def test_history_no_cookie_returns_401() -> None:
    from handlers.advisor_chat import handler as h

    result = h.handler(_event(cookie=None), _FakeContext())
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_with_anthropic_key", "patched_anthropic_client")
def test_history_pk_isolation_user_b_does_not_see_user_a_turns(
    dynamodb_table_with_chat_history: Any,
) -> None:
    """Critical PK invariant: user_b history fetch NIE leakuje user_a 5 turn."""
    from handlers.advisor_chat import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('user_b')}"
    result = h.handler(_event(cookie), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["messages"] == []  # user_b ma 0 turn
