"""Integration testy dla handlers.tdee_recalc — POST /api/tdee/recalc + cron.

Sprint 11.5 ADR-009 pivot — `DietCheckResult` zamiast `RecalcResult`.
Goal source = MANUAL `kcal_target` (nie Mifflin baseline). Drop wymóg
`tdee_baseline` — feature działa dla każdego z manualem.

PR1: handler bez LLM (narrative=None, PR2 dorzuci Haiku).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

FIXED_TODAY = date(2026, 5, 11)


class _FakeContext:
    aws_request_id = "test-req-id"


def _mint_test_jwt(user_id: str) -> str:
    from shared.auth import mint_jwt

    return mint_jwt(user_id)


_CSRF_TEST_TOKEN = "test-csrf-token-deterministic"


def _http_event(
    method: str,
    cookie: str | None,
    *,
    path: str = "/api/tdee/recalc",
    csrf: bool = True,
) -> dict[str, Any]:
    cookies: list[str] = [cookie] if cookie else []
    headers: dict[str, str] = {"content-type": "application/json"}
    if csrf and method not in {"GET", "HEAD", "OPTIONS"}:
        cookies.append(f"bodysync_csrf={_CSRF_TEST_TOKEN}")
        headers["x-csrf-token"] = _CSRF_TEST_TOKEN
    return {
        "version": "2.0",
        "routeKey": f"{method} {path}",
        "rawPath": path,
        "requestContext": {"http": {"method": method}},
        "headers": headers,
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
    kg_start: float = 80.0,
    kg_end: float | None = None,
    kcal: int = 2050,
) -> None:
    """Seed 14d window. Jeśli kg_end ustawione, ostatni dzień ma kg_end (else const)."""
    for i in range(days):
        day = today - timedelta(days=i)
        kg = kg_end if (kg_end is not None and i == 0) else kg_start
        _seed_weight(table, user_id, day=day, kg=kg)
        _seed_kcal_in(table, user_id, day=day, value=kcal)


@pytest.fixture
def freeze_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin handler `_today_factory` do FIXED_TODAY dla deterministic testów."""
    from handlers.tdee_recalc import handler as h

    monkeypatch.setattr(h, "_today_factory", lambda: FIXED_TODAY)


@pytest.fixture
def mock_llm(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Mock generate_narrative — domyślnie zwraca stub PL text. Test override
    przez setting `state["return_value"]` przed call (None = degradation)."""
    from handlers.tdee_recalc import handler as h

    state: dict[str, Any] = {"return_value": "Świetna robota — schudłeś zgodnie z planem."}

    def fake_generate(_result: Any) -> str | None:
        return state["return_value"]

    monkeypatch.setattr(h, "generate_narrative", fake_generate)
    return state


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


@pytest.mark.usefixtures("ssm_params", "dynamodb_table", "freeze_today")
def test_http_without_csrf_returns_403() -> None:
    """POST bez CSRF token → 403 (sec audit 2026-05-16 P1-4)."""
    from handlers.tdee_recalc import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_http_event("POST", cookie, csrf=False), _FakeContext())
    assert result["statusCode"] == 403


@pytest.mark.usefixtures("ssm_params", "freeze_today")
def test_http_profile_not_found_404(dynamodb_table: Any) -> None:
    from handlers.tdee_recalc import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('ghost')}"
    result = h.handler(_http_event("POST", cookie), _FakeContext())
    assert result["statusCode"] == 404


# ─── Happy path + persist ─────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params", "freeze_today", "mock_llm")
def test_http_returns_diet_check_result_with_narrative_and_persists(
    dynamodb_table: Any,
) -> None:
    """Owner z kcal_target=2250 + 14d danych → 200 z DietCheckResult + narrative."""
    from handlers.tdee_recalc import handler as h

    _seed_profile(dynamodb_table, "tomek", kcal_target=2250)
    _seed_window(dynamodb_table, "tomek", kg_start=80.0, kg_end=79.6, kcal=2050)

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_http_event("POST", cookie), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["skipped"] is False
    assert body["status"] == "on_track"
    assert body["goal_kcal"] == 2250
    assert body["kcal_in_avg"] == 2050
    assert body["narrative"] == "Świetna robota — schudłeś zgodnie z planem."
    assert body["narrative_unavailable"] is False

    profile = dynamodb_table.get_item(Key={"PK": "USER#tomek", "SK": "PROFILE"})["Item"]
    assert "diet_check_history" in profile
    assert len(profile["diet_check_history"]) == 1
    assert profile["diet_check_history"][0]["status"] == "on_track"
    assert profile["diet_check_history"][0]["narrative"] == (
        "Świetna robota — schudłeś zgodnie z planem."
    )
    assert profile["diet_check_last"]["status"] == "on_track"


@pytest.mark.usefixtures("ssm_params", "freeze_today")
def test_http_llm_unavailable_falls_back_to_deterministic_narrative_unavailable_true(
    dynamodb_table: Any, mock_llm: dict[str, Any]
) -> None:
    """LLM zwraca None (graceful degradation) → narrative=None,
    narrative_unavailable=True, persist mimo to (history zachowuje stats)."""
    from handlers.tdee_recalc import handler as h

    mock_llm["return_value"] = None  # Symuluj LLM unavailable.

    _seed_profile(dynamodb_table, "tomek", kcal_target=2250)
    _seed_window(dynamodb_table, "tomek", kg_start=80.0, kg_end=79.6, kcal=2050)

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_http_event("POST", cookie), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["skipped"] is False
    assert body["narrative"] is None
    assert body["narrative_unavailable"] is True
    assert body["status"] == "on_track"  # deterministic stats nadal są

    profile = dynamodb_table.get_item(Key={"PK": "USER#tomek", "SK": "PROFILE"})["Item"]
    assert profile["diet_check_history"][0]["narrative"] is None


# ─── Skip scenarios ────────────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params", "freeze_today")
def test_http_no_kcal_target_returns_skipped_200(dynamodb_table: Any) -> None:
    """PROFILE bez kcal_target → 200 z skipped=true (NIE 400)."""
    from handlers.tdee_recalc import handler as h

    _seed_profile(dynamodb_table, "tomek")  # bez kcal_target
    _seed_window(dynamodb_table, "tomek")

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_http_event("POST", cookie), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["skipped"] is True
    assert body["skip_reason"] == "no_kcal_target"


@pytest.mark.usefixtures("ssm_params", "freeze_today")
def test_http_insufficient_data_returns_skipped_200(dynamodb_table: Any) -> None:
    """8 wag (< 10) → skipped insufficient_weight_data."""
    from handlers.tdee_recalc import handler as h

    _seed_profile(dynamodb_table, "tomek", kcal_target=2250)
    for i in range(8):
        day = FIXED_TODAY - timedelta(days=i)
        _seed_weight(dynamodb_table, "tomek", day=day, kg=80.0)
    for i in range(14):
        day = FIXED_TODAY - timedelta(days=i)
        _seed_kcal_in(dynamodb_table, "tomek", day=day, value=2050)

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_http_event("POST", cookie), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["skipped"] is True
    assert body["skip_reason"] == "insufficient_weight_data"


# ─── PK isolation + history cap ────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params", "freeze_today", "mock_llm")
def test_http_pk_isolation_user_a_does_not_touch_user_b(
    dynamodb_table: Any,
) -> None:
    """JWT user_a → tylko user_a PROFILE update'd."""
    from handlers.tdee_recalc import handler as h

    _seed_profile(dynamodb_table, "tomek", kcal_target=2250)
    _seed_profile(dynamodb_table, "weronika", kcal_target=1900)
    _seed_window(dynamodb_table, "tomek", kg_start=80.0, kg_end=79.6, kcal=2050)
    _seed_window(dynamodb_table, "weronika", kg_start=60.0, kg_end=59.5, kcal=1700)

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_http_event("POST", cookie), _FakeContext())
    assert result["statusCode"] == 200

    weronika = dynamodb_table.get_item(Key={"PK": "USER#weronika", "SK": "PROFILE"})["Item"]
    assert "diet_check_history" not in weronika
    assert "diet_check_last" not in weronika


@pytest.mark.usefixtures("ssm_params", "freeze_today", "mock_llm")
def test_http_history_cap_10_fifo(dynamodb_table: Any) -> None:
    """10 history entries → next eval → drop oldest, append new = nadal 10."""
    from handlers.tdee_recalc import handler as h

    existing_history = [
        {
            "date": (FIXED_TODAY - timedelta(days=i * 14)).isoformat(),
            "skipped": False,
            "skip_reason": None,
            "goal_kcal": 2250,
            "kcal_in_avg": 2050,
            "waga_delta_kg": Decimal("-0.3"),
            "diff_kg": Decimal("0.0"),
            "status": "on_track",
            "narrative": None,
        }
        for i in range(10, 0, -1)
    ]
    _seed_profile(
        dynamodb_table,
        "tomek",
        kcal_target=2250,
        diet_check_history=existing_history,
    )
    _seed_window(dynamodb_table, "tomek", kg_start=80.0, kg_end=79.6, kcal=2050)

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_http_event("POST", cookie), _FakeContext())
    assert result["statusCode"] == 200

    profile = dynamodb_table.get_item(Key={"PK": "USER#tomek", "SK": "PROFILE"})["Item"]
    assert len(profile["diet_check_history"]) == 10
    assert profile["diet_check_history"][-1]["date"] == FIXED_TODAY.isoformat()
    oldest = existing_history[0]["date"]
    assert all(e["date"] != oldest for e in profile["diet_check_history"])


# ─── Cron path ─────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params", "freeze_today", "mock_llm")
def test_cron_iterates_user_list(dynamodb_table: Any) -> None:
    from handlers.tdee_recalc import handler as h

    _seed_profile(dynamodb_table, "tomek", kcal_target=2250)
    _seed_profile(dynamodb_table, "weronika", kcal_target=1900)
    _seed_window(dynamodb_table, "tomek", kg_start=80.0, kg_end=79.6, kcal=2050)
    _seed_window(dynamodb_table, "weronika", kg_start=60.0, kg_end=59.5, kcal=1700)

    summary = h.handler(_cron_event(["tomek", "weronika"]), _FakeContext())

    assert summary == {
        "users": 2,
        "evaluated": 2,
        "skipped": 0,
        "errored": 0,
    }


@pytest.mark.usefixtures("ssm_params", "freeze_today", "mock_llm")
def test_cron_per_user_error_isolation(dynamodb_table: Any) -> None:
    """user_a missing PROFILE → user_b nadal processed."""
    from handlers.tdee_recalc import handler as h

    _seed_profile(dynamodb_table, "weronika", kcal_target=1900)
    _seed_window(dynamodb_table, "weronika", kg_start=60.0, kg_end=59.5, kcal=1700)

    summary = h.handler(_cron_event(["ghost", "weronika"]), _FakeContext())

    assert summary["users"] == 2
    assert summary["evaluated"] == 1
    assert summary["errored"] == 1


@pytest.mark.usefixtures("ssm_params", "freeze_today")
def test_cron_summary_skipped_count(dynamodb_table: Any) -> None:
    """Owner z brakiem kcal_target → skipped=1, nie errored."""
    from handlers.tdee_recalc import handler as h

    _seed_profile(dynamodb_table, "tomek")
    _seed_window(dynamodb_table, "tomek")

    summary = h.handler(_cron_event(["tomek"]), _FakeContext())

    assert summary == {
        "users": 1,
        "evaluated": 0,
        "skipped": 1,
        "errored": 0,
    }
