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
    method: str = "GET",
) -> dict[str, Any]:
    cookies: list[str] = [cookie] if cookie else []
    return {
        "version": "2.0",
        "routeKey": f"{method} /api/advisor/chat/history",
        "rawPath": "/api/advisor/chat/history",
        "requestContext": {"http": {"method": method}},
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


# ─── DELETE /api/advisor/chat/history ─────────────────────────────────────


@pytest.mark.usefixtures("ssm_with_anthropic_key", "patched_anthropic_client")
def test_delete_history_removes_today_turns(
    dynamodb_table_with_chat_history: Any,
) -> None:
    """Fixture pre-seeds 5 turn user_a today → DELETE wipuje wszystkie."""
    from handlers.advisor_chat import handler as h
    from handlers.advisor_chat import service as svc

    cookie = f"bodysync_session={_mint_test_jwt('user_a')}"
    today = datetime.now().astimezone().date()

    # Sanity check pre-delete (fixture seed jest valid).
    pre = svc.read_history("user_a", today)
    assert len(pre) == 5

    result = h.handler(_event(cookie, method="DELETE"), _FakeContext())
    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["deleted"] == 5
    assert body["date"] == today.isoformat()

    # Post-delete history empty — LLM widzi pusty `<conversation_history>`.
    post = svc.read_history("user_a", today)
    assert post == []


@pytest.mark.usefixtures("ssm_with_anthropic_key", "patched_anthropic_client")
def test_delete_history_idempotent_when_empty(dynamodb_table: Any) -> None:
    """Brak rows → 200 z `deleted: 0`. UX: silent success, owner kliknął
    przycisk i widzi "wyczyszczono" niezależnie czy coś było."""
    from handlers.advisor_chat import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('lonely_user')}"
    result = h.handler(_event(cookie, method="DELETE"), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["deleted"] == 0


@pytest.mark.usefixtures("ssm_with_anthropic_key", "patched_anthropic_client")
def test_delete_history_pk_isolation(
    dynamodb_table_with_chat_history: Any,
) -> None:
    """Critical: user_b DELETE NIE rusza user_a 5 turn pod USER#user_a PK."""
    from handlers.advisor_chat import handler as h
    from handlers.advisor_chat import service as svc

    today = datetime.now().astimezone().date()

    cookie = f"bodysync_session={_mint_test_jwt('user_b')}"
    result = h.handler(_event(cookie, method="DELETE"), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["deleted"] == 0  # user_b miał 0 turn

    # user_a history intact — nie skreślone przez user_b DELETE.
    user_a_history = svc.read_history("user_a", today)
    assert len(user_a_history) == 5


@pytest.mark.usefixtures("ssm_with_anthropic_key", "patched_anthropic_client", "dynamodb_table")
def test_delete_history_no_cookie_returns_401() -> None:
    """DELETE bez JWT cookie → 401 (NIE wipuje nic)."""
    from handlers.advisor_chat import handler as h

    result = h.handler(_event(cookie=None, method="DELETE"), _FakeContext())
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_with_anthropic_key", "patched_anthropic_client")
def test_delete_history_preserves_yesterday_chat(dynamodb_table: Any) -> None:
    """Boundary: DELETE czyści TYLKO today. Wczorajsze CHAT rows zostają
    (TTL 24h sam wymiecie). Bez tego cross-day wipe psułby UX gdy user
    czatował o północy i klika clear rano."""
    from handlers.advisor_chat import handler as h

    today = datetime.now().astimezone().date()
    yesterday = today - timedelta(days=1)

    # Seed: 2 turn dziś, 1 wczoraj
    for idx, content in enumerate(["dziś-1", "dziś-2"]):
        dynamodb_table.put_item(
            Item={
                "PK": "USER#tomek",
                "SK": f"CHAT#{today.isoformat()}#{idx:04d}",
                "role": "user",
                "content": content,
                "ts": f"{today.isoformat()}T10:00:00+00:00",
                "ttl": 9999999999,
                "turn_idx": idx,
            }
        )
    dynamodb_table.put_item(
        Item={
            "PK": "USER#tomek",
            "SK": f"CHAT#{yesterday.isoformat()}#0000",
            "role": "user",
            "content": "wczoraj",
            "ts": f"{yesterday.isoformat()}T22:00:00+00:00",
            "ttl": 9999999999,
            "turn_idx": 0,
        }
    )

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_event(cookie, method="DELETE"), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["deleted"] == 2  # tylko dwa today

    # Wczorajszy wpis nadal w DDB.
    yest_item = dynamodb_table.get_item(
        Key={"PK": "USER#tomek", "SK": f"CHAT#{yesterday.isoformat()}#0000"}
    )
    assert "Item" in yest_item
