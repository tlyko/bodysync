"""Integration testy dla handlers.tdee_recalc — POST /api/tdee/recalc + cron.

10 testów: HTTP auth (3), happy path persist (1), skip scenarios (2),
PK isolation (1), cron iteration (3).

Macros sync test (kcal_target propaguje z tdee_adaptive) odłożony do PR4 —
PR2 minimal scope: persist tdee_adaptive + tdee_last_recalc + tdee_history.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

FIXED_TODAY = date(2026, 5, 11)
WINDOW_START = date(2026, 4, 28)


class _FakeContext:
    aws_request_id = "test-req-id"


def _mint_test_jwt(user_id: str) -> str:
    from shared.auth import mint_jwt

    return mint_jwt(user_id)


def _http_event(
    method: str, cookie: str | None, *, path: str = "/api/tdee/recalc"
) -> dict[str, Any]:
    cookies: list[str] = [cookie] if cookie else []
    return {
        "version": "2.0",
        "routeKey": f"{method} {path}",
        "rawPath": path,
        "requestContext": {"http": {"method": method}},
        "headers": {"content-type": "application/json"},
        "cookies": cookies,
        "body": None,
        "isBase64Encoded": False,
    }


def _cron_event(users: list[str]) -> dict[str, Any]:
    return {"users": users}


def _seed_profile(table: Any, user_id: str, **extra_attrs: Any) -> None:
    item: dict[str, Any] = {
        "PK": f"USER#{user_id}",
        "SK": "PROFILE",
        "email": f"{user_id}@example.com",
        "name": user_id,
        **extra_attrs,
    }
    table.put_item(Item=item)


def _seed_weight(table: Any, user_id: str, *, day: date, kg: float) -> None:
    table.put_item(
        Item={
            "PK": f"USER#{user_id}",
            "SK": f"BIOMETRY#{day.isoformat()}#weight",
            "kg": Decimal(str(kg)),
        }
    )


def _seed_kcal_in(table: Any, user_id: str, *, day: date, value: int) -> None:
    table.put_item(
        Item={
            "PK": f"USER#{user_id}",
            "SK": f"BIOMETRY#{day.isoformat()}#kcal_in#{day.isoformat()}T00:00:00",
            "value": Decimal(str(value)),
        }
    )


def _seed_window(
    table: Any,
    user_id: str,
    *,
    today: date = FIXED_TODAY,
    days: int = 14,
    kg: float = 80.0,
    kcal: int = 2080,
) -> None:
    for i in range(days):
        day = today - timedelta(days=i)
        _seed_weight(table, user_id, day=day, kg=kg)
        _seed_kcal_in(table, user_id, day=day, value=kcal)


@pytest.fixture
def freeze_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin handler `_today_factory` do FIXED_TODAY dla deterministic testów."""
    from handlers.tdee_recalc import handler as h

    monkeypatch.setattr(h, "_today_factory", lambda: FIXED_TODAY)


# ─── HTTP auth ─────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params", "dynamodb_table", "freeze_today")
def test_http_unauthenticated_401() -> None:
    from handlers.tdee_recalc import handler as h

    result = h.handler(_http_event("POST", cookie=None), _FakeContext())
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_params", "dynamodb_table", "freeze_today")
def test_http_invalid_jwt_401() -> None:
    from handlers.tdee_recalc import handler as h

    cookie = "bodysync_session=not-a-valid-jwt"
    result = h.handler(_http_event("POST", cookie), _FakeContext())
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_params", "freeze_today")
def test_http_profile_not_found_404(dynamodb_table: Any) -> None:
    from handlers.tdee_recalc import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('ghost')}"
    result = h.handler(_http_event("POST", cookie), _FakeContext())
    assert result["statusCode"] == 404


# ─── Happy path + persist ──────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params", "freeze_today")
def test_http_recalc_persists_tdee_adaptive_and_appends_history(
    dynamodb_table: Any,
) -> None:
    """Owner zjadł deficyt 200 kcal/dzień przez 14d, waga zero zmiany.
    Recalc zwraca adjustment=-150 (capped), TDEE 2280→2130. Persist do PROFILE.
    """
    from handlers.tdee_recalc import handler as h

    _seed_profile(dynamodb_table, "tomek", tdee_baseline=2280, tdee_adaptive=2280)
    _seed_window(dynamodb_table, "tomek", kg=80.0, kcal=2080)

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_http_event("POST", cookie), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["skipped"] is False
    assert body["tdee_after"] == 2130
    assert body["adjustment"] == -150
    assert body["capped"] is True

    profile = dynamodb_table.get_item(Key={"PK": "USER#tomek", "SK": "PROFILE"})["Item"]
    assert int(profile["tdee_adaptive"]) == 2130
    assert profile["tdee_last_recalc"]["after"] == 2130
    assert len(profile["tdee_history"]) == 1
    assert profile["tdee_history"][0]["event"] == "recalc"


# ─── Skip scenarios ────────────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params", "freeze_today")
def test_http_skipped_returns_200_not_400(dynamodb_table: Any) -> None:
    """Insufficient data (8 wags zamiast 10+) → 200 z skipped=true (NIE 400)."""
    from handlers.tdee_recalc import handler as h

    _seed_profile(dynamodb_table, "tomek", tdee_baseline=2280, tdee_adaptive=2280)
    for i in range(8):
        day = FIXED_TODAY - timedelta(days=i)
        _seed_weight(dynamodb_table, "tomek", day=day, kg=80.0)
    for i in range(14):
        day = FIXED_TODAY - timedelta(days=i)
        _seed_kcal_in(dynamodb_table, "tomek", day=day, value=2080)

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_http_event("POST", cookie), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["skipped"] is True
    assert body["reason"] == "insufficient_weight_data"

    profile = dynamodb_table.get_item(Key={"PK": "USER#tomek", "SK": "PROFILE"})["Item"]
    assert int(profile["tdee_adaptive"]) == 2280
    assert profile["tdee_last_recalc"]["event"] == "skipped"
    assert profile["tdee_last_recalc"]["reason"] == "insufficient_weight_data"


@pytest.mark.usefixtures("ssm_params", "freeze_today")
def test_http_baseline_not_initialized_skipped(dynamodb_table: Any) -> None:
    """Owner ma PROFILE ale brak tdee_baseline (PR4 init body_profile)."""
    from handlers.tdee_recalc import handler as h

    _seed_profile(dynamodb_table, "tomek")
    _seed_window(dynamodb_table, "tomek")

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_http_event("POST", cookie), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["skipped"] is True
    assert body["reason"] == "baseline_not_initialized"


# ─── PK isolation + history cap ────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params", "freeze_today")
def test_http_pk_isolation_user_a_does_not_touch_user_b(
    dynamodb_table: Any,
) -> None:
    """JWT user_a → tylko user_a PROFILE update'd, user_b nietknięty."""
    from handlers.tdee_recalc import handler as h

    _seed_profile(dynamodb_table, "tomek", tdee_baseline=2280, tdee_adaptive=2280)
    _seed_profile(dynamodb_table, "weronika", tdee_baseline=1900, tdee_adaptive=1900)
    _seed_window(dynamodb_table, "tomek", kg=80.0, kcal=2080)
    _seed_window(dynamodb_table, "weronika", kg=60.0, kcal=1700)

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_http_event("POST", cookie), _FakeContext())
    assert result["statusCode"] == 200

    weronika = dynamodb_table.get_item(Key={"PK": "USER#weronika", "SK": "PROFILE"})["Item"]
    assert int(weronika["tdee_adaptive"]) == 1900
    assert "tdee_last_recalc" not in weronika
    assert "tdee_history" not in weronika


@pytest.mark.usefixtures("ssm_params", "freeze_today")
def test_http_history_cap_20_fifo(dynamodb_table: Any) -> None:
    """20 history entries → recalc → drop oldest, append new = nadal 20."""
    from handlers.tdee_recalc import handler as h

    existing_history = [
        {
            "date": (FIXED_TODAY - timedelta(days=i * 14)).isoformat(),
            "event": "recalc",
            "before": 2280,
            "after": 2280,
            "kcal_in_avg": 2080,
            "waga_delta_kg": Decimal("0"),
            "adjustment": 0,
            "capped": False,
            "reason": None,
        }
        for i in range(20, 0, -1)
    ]
    _seed_profile(
        dynamodb_table,
        "tomek",
        tdee_baseline=2280,
        tdee_adaptive=2280,
        tdee_history=existing_history,
    )
    _seed_window(dynamodb_table, "tomek")

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_http_event("POST", cookie), _FakeContext())
    assert result["statusCode"] == 200

    profile = dynamodb_table.get_item(Key={"PK": "USER#tomek", "SK": "PROFILE"})["Item"]
    assert len(profile["tdee_history"]) == 20
    assert profile["tdee_history"][-1]["date"] == FIXED_TODAY.isoformat()
    oldest = existing_history[0]["date"]
    assert all(entry["date"] != oldest for entry in profile["tdee_history"])


# ─── Cron path ─────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params", "freeze_today")
def test_cron_iterates_user_list(dynamodb_table: Any) -> None:
    from handlers.tdee_recalc import handler as h

    _seed_profile(dynamodb_table, "tomek", tdee_baseline=2280, tdee_adaptive=2280)
    _seed_profile(dynamodb_table, "weronika", tdee_baseline=1900, tdee_adaptive=1900)
    _seed_window(dynamodb_table, "tomek", kg=80.0, kcal=2080)
    _seed_window(dynamodb_table, "weronika", kg=60.0, kcal=1700)

    summary = h.handler(_cron_event(["tomek", "weronika"]), _FakeContext())

    assert summary == {
        "users": 2,
        "recalculated": 2,
        "skipped": 0,
        "errored": 0,
    }
    tomek = dynamodb_table.get_item(Key={"PK": "USER#tomek", "SK": "PROFILE"})["Item"]
    weronika = dynamodb_table.get_item(Key={"PK": "USER#weronika", "SK": "PROFILE"})["Item"]
    assert "tdee_last_recalc" in tomek
    assert "tdee_last_recalc" in weronika


@pytest.mark.usefixtures("ssm_params", "freeze_today")
def test_cron_per_user_error_isolation(dynamodb_table: Any) -> None:
    """user_a missing PROFILE (raises) → user_b nadal processed."""
    from handlers.tdee_recalc import handler as h

    _seed_profile(dynamodb_table, "weronika", tdee_baseline=1900, tdee_adaptive=1900)
    _seed_window(dynamodb_table, "weronika", kg=60.0, kcal=1700)

    summary = h.handler(_cron_event(["ghost", "weronika"]), _FakeContext())

    assert summary["users"] == 2
    assert summary["recalculated"] == 1
    assert summary["errored"] == 1
    weronika = dynamodb_table.get_item(Key={"PK": "USER#weronika", "SK": "PROFILE"})["Item"]
    assert "tdee_last_recalc" in weronika


@pytest.mark.usefixtures("ssm_params", "freeze_today")
def test_cron_summary_skipped_count(dynamodb_table: Any) -> None:
    """Owner z brakiem baseline → skipped=1, nie errored."""
    from handlers.tdee_recalc import handler as h

    _seed_profile(dynamodb_table, "tomek")
    _seed_window(dynamodb_table, "tomek")

    summary = h.handler(_cron_event(["tomek"]), _FakeContext())

    assert summary == {
        "users": 1,
        "recalculated": 0,
        "skipped": 1,
        "errored": 0,
    }
