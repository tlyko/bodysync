"""Tests dla GET /api/plan handler."""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import MagicMock, patch

import boto3
import pytest


def _event(
    method: str = "GET",
    cookie: str | None = None,
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    qs: dict[str, str] = {}
    if refresh:
        qs["refresh"] = "1"
    return {
        "version": "2.0",
        "routeKey": f"{method} /api/plan",
        "rawPath": "/api/plan",
        "requestContext": {"http": {"method": method}},
        "headers": {"content-type": "application/json"},
        "cookies": [cookie] if cookie else [],
        "queryStringParameters": qs or None,
        "body": None,
        "isBase64Encoded": False,
    }


class _FakeContext:
    aws_request_id = "test-req-id"


def _mint_test_jwt(user_id: str) -> str:
    from shared.auth import mint_jwt

    return mint_jwt(user_id)


@pytest.fixture
def plan_ssm(ssm_params: None) -> None:
    """Pre-seed Google Sheets SSM params dla user 'tomek'."""
    client = boto3.client("ssm", region_name="eu-west-1")
    client.put_parameter(
        Name="/bodysync/google/service_account_json",
        Value=json.dumps(
            {
                "type": "service_account",
                "project_id": "test-proj",
                "private_key_id": "kid",
                "private_key": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n",
                "client_email": "bodysync-sheets@test-proj.iam.gserviceaccount.com",
                "client_id": "0",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        ),
        Type="SecureString",
    )
    client.put_parameter(
        Name="/bodysync/tomek/training-sheet-id",
        Value="1AbCdEfGhIjKlMnOpQrStUvWxYz",
        Type="String",
    )
    client.put_parameter(
        Name="/bodysync/tomek/training-sheet-tab",
        Value="Arkusz5",
        Type="String",
    )
    from shared import ssm as _ssm

    _ssm.clear_cache()


def _patch_sheets_returning(rows: list[list[str]]) -> Any:
    """Build fake googleapi service chain z given rows."""
    fake = MagicMock()
    fake.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        "values": rows
    }
    return patch("handlers.plan.service.build", return_value=fake)


def _patch_credentials() -> Any:
    return patch(
        "google.oauth2.service_account.Credentials.from_service_account_info",
        return_value=MagicMock(),
    )


# ─── Auth ─────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("plan_ssm", "dynamodb_table")
def test_missing_cookie_returns_401() -> None:
    from handlers.plan import handler as h

    result = h.handler(_event(cookie=None), _FakeContext())
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("plan_ssm", "dynamodb_table")
def test_invalid_jwt_returns_401() -> None:
    from handlers.plan import handler as h

    result = h.handler(_event(cookie="bodysync_session=invalid-token"), _FakeContext())
    assert result["statusCode"] == 401


# ─── Config errors ────────────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_missing_ssm_config_returns_503() -> None:
    """Brak training-sheet-id w SSM → 503 not_configured."""
    from handlers.plan import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_event(cookie=cookie), _FakeContext())
    assert result["statusCode"] == 503
    assert json.loads(result["body"])["error"] == "not_configured"


@pytest.mark.usefixtures("dynamodb_table")
def test_placeholder_ssm_config_returns_503(ssm_params: None) -> None:
    """SSM ma 'PLACEHOLDER' → 503 (initial deploy state, owner jeszcze nie wpisał)."""
    from handlers.plan import handler as h

    client = boto3.client("ssm", region_name="eu-west-1")
    client.put_parameter(
        Name="/bodysync/google/service_account_json",
        Value="PLACEHOLDER",
        Type="SecureString",
    )
    client.put_parameter(
        Name="/bodysync/tomek/training-sheet-id",
        Value="PLACEHOLDER",
        Type="String",
    )
    client.put_parameter(
        Name="/bodysync/tomek/training-sheet-tab",
        Value="PLACEHOLDER",
        Type="String",
    )
    from shared import ssm as _ssm

    _ssm.clear_cache()

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_event(cookie=cookie), _FakeContext())
    assert result["statusCode"] == 503
    assert json.loads(result["body"])["error"] == "not_configured"


# ─── Happy path ───────────────────────────────────────────────────────────


@pytest.mark.usefixtures("plan_ssm")
def test_happy_path_fetches_sheet_and_caches_to_ddb(dynamodb_table: Any) -> None:
    from handlers.plan import handler as h
    from shared.dynamo import get_item

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    rows = [["Trening A", "Squat", "5x5"], ["", "Bench", "5x5"]]

    with _patch_sheets_returning(rows), _patch_credentials():
        result = h.handler(_event(cookie=cookie), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["rows"] == rows
    assert body["fresh"] is True
    assert body["sheet_tab"] == "Arkusz5"
    assert isinstance(body["fetched_at"], int)

    # DDB cache row persisted
    cached = get_item("USER#tomek", "PLAN#current")
    assert cached is not None
    assert cached["rows"] == rows
    assert cached["sheet_tab"] == "Arkusz5"


# ─── Cache hit ────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("plan_ssm")
def test_cache_hit_returns_cached_with_fresh_false(dynamodb_table: Any) -> None:
    """Drugi request w ciągu 15min — DDB hit, fresh=False, NIE wywołuje Google API."""
    from handlers.plan import handler as h
    from handlers.plan.schemas import CachedPlan
    from handlers.plan.service import save_cached_plan

    save_cached_plan(
        "tomek",
        CachedPlan(
            rows=[["cached row"]],
            fetched_at=int(time.time()) - 60,  # 1min ago
            sheet_tab="Arkusz5",
        ),
    )

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    # Patch build żeby fail jeśli ktoś go wywoła (cache hit nie powinien)
    with patch("handlers.plan.service.build") as build_mock:
        result = h.handler(_event(cookie=cookie), _FakeContext())
        build_mock.assert_not_called()

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["rows"] == [["cached row"]]
    assert body["fresh"] is False


# ─── Force refresh bypass ─────────────────────────────────────────────────


@pytest.mark.usefixtures("plan_ssm")
def test_force_refresh_bypasses_cache(dynamodb_table: Any) -> None:
    """?refresh=1 → fetch z Sheets nawet gdy cache jest świeży."""
    from handlers.plan import handler as h
    from handlers.plan.schemas import CachedPlan
    from handlers.plan.service import save_cached_plan

    save_cached_plan(
        "tomek",
        CachedPlan(
            rows=[["stale cache row"]],
            fetched_at=int(time.time()) - 60,
            sheet_tab="Arkusz5",
        ),
    )

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    fresh_rows = [["fresh row 1"], ["fresh row 2"]]

    with _patch_sheets_returning(fresh_rows), _patch_credentials():
        result = h.handler(_event(cookie=cookie, refresh=True), _FakeContext())

    body = json.loads(result["body"])
    assert body["rows"] == fresh_rows
    assert body["fresh"] is True


# ─── Stale fallback when Google API down ──────────────────────────────────


@pytest.mark.usefixtures("plan_ssm")
def test_google_api_down_serves_stale_cache(dynamodb_table: Any) -> None:
    """Cache STALE (>15min) + Google API zwróci błąd → return stale, fresh=False."""
    from googleapiclient.errors import HttpError

    from handlers.plan import handler as h
    from handlers.plan.schemas import CachedPlan
    from handlers.plan.service import save_cached_plan

    stale_ts = int(time.time()) - 3600  # 1h ago, past TTL
    save_cached_plan(
        "tomek",
        CachedPlan(
            rows=[["stale row"]],
            fetched_at=stale_ts,
            sheet_tab="Arkusz5",
        ),
    )

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    fake = MagicMock()
    resp = MagicMock()
    resp.status = 500
    resp.reason = "test"
    fake.spreadsheets.return_value.values.return_value.get.return_value.execute.side_effect = (
        HttpError(resp=resp, content=b"{}")
    )

    with patch("handlers.plan.service.build", return_value=fake), _patch_credentials():
        result = h.handler(_event(cookie=cookie), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["rows"] == [["stale row"]]
    assert body["fresh"] is False
    assert body["fetched_at"] == stale_ts


@pytest.mark.usefixtures("plan_ssm")
def test_google_api_down_no_cache_returns_502(dynamodb_table: Any) -> None:
    """Google API błąd + brak cache → 502 (zwykły API error, nie config issue)."""
    from googleapiclient.errors import HttpError

    from handlers.plan import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    fake = MagicMock()
    resp = MagicMock()
    resp.status = 500
    resp.reason = "test"
    fake.spreadsheets.return_value.values.return_value.get.return_value.execute.side_effect = (
        HttpError(resp=resp, content=b"{}")
    )

    with patch("handlers.plan.service.build", return_value=fake), _patch_credentials():
        result = h.handler(_event(cookie=cookie), _FakeContext())

    assert result["statusCode"] == 502
    assert json.loads(result["body"])["error"] == "sheets_api_error"


@pytest.mark.usefixtures("plan_ssm")
def test_permission_denied_no_cache_returns_503(dynamodb_table: Any) -> None:
    """403 z Sheets (SA brak dostępu) + brak cache → 503 (config issue, nie API down)."""
    from googleapiclient.errors import HttpError

    from handlers.plan import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    fake = MagicMock()
    resp = MagicMock()
    resp.status = 403
    fake.spreadsheets.return_value.values.return_value.get.return_value.execute.side_effect = (
        HttpError(resp=resp, content=b"{}")
    )

    with patch("handlers.plan.service.build", return_value=fake), _patch_credentials():
        result = h.handler(_event(cookie=cookie), _FakeContext())

    assert result["statusCode"] == 503
    assert json.loads(result["body"])["error"] == "permission_denied"


# ─── PK isolation ─────────────────────────────────────────────────────────


@pytest.mark.usefixtures("plan_ssm")
def test_pk_isolation_two_users_separate_cache(dynamodb_table: Any) -> None:
    """tomek + weronika osobne SSM paths + osobne DDB cache rows."""
    from handlers.plan import handler as h
    from shared.dynamo import get_item

    # Pre-seed weronika SSM
    client = boto3.client("ssm", region_name="eu-west-1")
    client.put_parameter(
        Name="/bodysync/weronika/training-sheet-id",
        Value="2W_W_W_W_W",
        Type="String",
    )
    client.put_parameter(
        Name="/bodysync/weronika/training-sheet-tab",
        Value="Tydz1",
        Type="String",
    )
    from shared import ssm as _ssm

    _ssm.clear_cache()

    tomek_cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    weronika_cookie = f"bodysync_session={_mint_test_jwt('weronika')}"

    with _patch_sheets_returning([["tomek-data"]]), _patch_credentials():
        h.handler(_event(cookie=tomek_cookie), _FakeContext())
    with _patch_sheets_returning([["weronika-data"]]), _patch_credentials():
        h.handler(_event(cookie=weronika_cookie), _FakeContext())

    tomek_cached = get_item("USER#tomek", "PLAN#current")
    weronika_cached = get_item("USER#weronika", "PLAN#current")
    assert tomek_cached is not None and tomek_cached["rows"] == [["tomek-data"]]
    assert weronika_cached is not None and weronika_cached["rows"] == [["weronika-data"]]
    assert tomek_cached["sheet_tab"] == "Arkusz5"
    assert weronika_cached["sheet_tab"] == "Tydz1"
