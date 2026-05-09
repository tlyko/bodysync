"""Tests dla plan service module — pure logic z mocked googleapi.

Test surface:
- fetch_sheet_values happy path (z mocked googleapi service builder)
- error mapping: invalid JSON, 404, 403, generic HttpError, unexpected exc
- jagged row padding (Google API zwraca rows różnej długości)
- DDB cache load/save round-trip + TTL freshness check
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

# ─── fetch_sheet_values ───────────────────────────────────────────────────


def _fake_sheets_service(values: list[list[Any]] | None) -> MagicMock:
    """Build a chain matching service.spreadsheets().values().get(...).execute()."""
    service = MagicMock()
    service.spreadsheets.return_value.values.return_value.get.return_value.execute.return_value = {
        "values": values
    }
    return service


def _http_error(status: int) -> HttpError:
    """Construct googleapiclient HttpError z konkretnym status code."""
    resp = MagicMock()
    resp.status = status
    resp.reason = "test"
    return HttpError(resp=resp, content=b"{}")


def _valid_creds_json() -> str:
    """Minimal SA credentials JSON — service_account.Credentials.from_service_account_info
    wymaga `type=service_account` + `client_email` + `token_uri` + `private_key`."""
    return json.dumps(
        {
            "type": "service_account",
            "project_id": "test-proj",
            "private_key_id": "kid",
            "private_key": "-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----\n",
            "client_email": "bodysync-sheets@test-proj.iam.gserviceaccount.com",
            "client_id": "0",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


def test_fetch_sheet_values_happy_path() -> None:
    from handlers.plan.service import fetch_sheet_values

    fake = _fake_sheets_service([["a", "b"], ["c", "d"]])
    with (
        patch("handlers.plan.service.build", return_value=fake),
        patch(
            "google.oauth2.service_account.Credentials.from_service_account_info",
            return_value=MagicMock(),
        ),
    ):
        rows = fetch_sheet_values("sheet-id", "Arkusz5", _valid_creds_json())

    assert rows == [["a", "b"], ["c", "d"]]


def test_fetch_sheet_values_pads_jagged_rows() -> None:
    """Google Sheets API drop'uje trailing empty cells — pad'ujemy do max width."""
    from handlers.plan.service import fetch_sheet_values

    fake = _fake_sheets_service([["a", "b", "c"], ["d", "e"], ["f"]])
    with (
        patch("handlers.plan.service.build", return_value=fake),
        patch(
            "google.oauth2.service_account.Credentials.from_service_account_info",
            return_value=MagicMock(),
        ),
    ):
        rows = fetch_sheet_values("sheet-id", "Arkusz5", _valid_creds_json())

    assert rows == [["a", "b", "c"], ["d", "e", ""], ["f", "", ""]]


def test_fetch_sheet_values_casts_non_string_cells() -> None:
    """FORMATTED_VALUE default daje string ale defensywnie cast'ujemy int/float."""
    from handlers.plan.service import fetch_sheet_values

    fake = _fake_sheets_service([[1, 2.5, None, "ok"]])
    with (
        patch("handlers.plan.service.build", return_value=fake),
        patch(
            "google.oauth2.service_account.Credentials.from_service_account_info",
            return_value=MagicMock(),
        ),
    ):
        rows = fetch_sheet_values("sheet-id", "Arkusz5", _valid_creds_json())

    assert rows == [["1", "2.5", "", "ok"]]


def test_fetch_sheet_values_empty_sheet_returns_empty_list() -> None:
    from handlers.plan.service import fetch_sheet_values

    fake = _fake_sheets_service(None)
    with (
        patch("handlers.plan.service.build", return_value=fake),
        patch(
            "google.oauth2.service_account.Credentials.from_service_account_info",
            return_value=MagicMock(),
        ),
    ):
        rows = fetch_sheet_values("sheet-id", "Arkusz5", _valid_creds_json())

    assert rows == []


def test_fetch_sheet_values_invalid_credentials_json() -> None:
    from handlers.plan.service import PlanFetchError, fetch_sheet_values

    with pytest.raises(PlanFetchError) as exc:
        fetch_sheet_values("sheet-id", "Arkusz5", "not-json{{{")

    assert exc.value.reason == "invalid_credentials_json"


def test_fetch_sheet_values_invalid_credentials_format() -> None:
    """Valid JSON ale brakujące `type` / `client_email` → ValueError z google-auth."""
    from handlers.plan.service import PlanFetchError, fetch_sheet_values

    with (
        patch(
            "google.oauth2.service_account.Credentials.from_service_account_info",
            side_effect=ValueError("Service account info was not in the expected format"),
        ),
        pytest.raises(PlanFetchError) as exc,
    ):
        fetch_sheet_values("sheet-id", "Arkusz5", '{"type": "user"}')

    assert exc.value.reason == "invalid_credentials_format"


def test_fetch_sheet_values_404_maps_to_sheet_not_found() -> None:
    from handlers.plan.service import PlanFetchError, fetch_sheet_values

    fake = MagicMock()
    fake.spreadsheets.return_value.values.return_value.get.return_value.execute.side_effect = (
        _http_error(404)
    )
    with (
        patch("handlers.plan.service.build", return_value=fake),
        patch(
            "google.oauth2.service_account.Credentials.from_service_account_info",
            return_value=MagicMock(),
        ),
        pytest.raises(PlanFetchError) as exc,
    ):
        fetch_sheet_values("sheet-id", "MissingTab", _valid_creds_json())

    assert exc.value.reason == "sheet_not_found_or_no_access"


def test_fetch_sheet_values_403_maps_to_permission_denied() -> None:
    from handlers.plan.service import PlanFetchError, fetch_sheet_values

    fake = MagicMock()
    fake.spreadsheets.return_value.values.return_value.get.return_value.execute.side_effect = (
        _http_error(403)
    )
    with (
        patch("handlers.plan.service.build", return_value=fake),
        patch(
            "google.oauth2.service_account.Credentials.from_service_account_info",
            return_value=MagicMock(),
        ),
        pytest.raises(PlanFetchError) as exc,
    ):
        fetch_sheet_values("sheet-id", "Arkusz5", _valid_creds_json())

    assert exc.value.reason == "permission_denied"


def test_fetch_sheet_values_generic_http_error_maps_to_sheets_api_error() -> None:
    from handlers.plan.service import PlanFetchError, fetch_sheet_values

    fake = MagicMock()
    fake.spreadsheets.return_value.values.return_value.get.return_value.execute.side_effect = (
        _http_error(500)
    )
    with (
        patch("handlers.plan.service.build", return_value=fake),
        patch(
            "google.oauth2.service_account.Credentials.from_service_account_info",
            return_value=MagicMock(),
        ),
        pytest.raises(PlanFetchError) as exc,
    ):
        fetch_sheet_values("sheet-id", "Arkusz5", _valid_creds_json())

    assert exc.value.reason == "sheets_api_error"


def test_fetch_sheet_values_unexpected_exception_maps_to_sheets_api_error() -> None:
    """Network glitch, SSL handshake fail, etc. — fall-through bucket."""
    from handlers.plan.service import PlanFetchError, fetch_sheet_values

    fake = MagicMock()
    fake.spreadsheets.return_value.values.return_value.get.return_value.execute.side_effect = (
        ConnectionError("boom")
    )
    with (
        patch("handlers.plan.service.build", return_value=fake),
        patch(
            "google.oauth2.service_account.Credentials.from_service_account_info",
            return_value=MagicMock(),
        ),
        pytest.raises(PlanFetchError) as exc,
    ):
        fetch_sheet_values("sheet-id", "Arkusz5", _valid_creds_json())

    assert exc.value.reason == "sheets_api_error"


# ─── DDB cache round-trip ─────────────────────────────────────────────────


def test_save_and_load_cached_plan_round_trip(dynamodb_table: Any) -> None:
    from handlers.plan.schemas import CachedPlan
    from handlers.plan.service import load_cached_plan, save_cached_plan

    plan = CachedPlan(
        rows=[["Trening A", "5x5"], ["Squat", "60kg"]],
        fetched_at=1_700_000_000,
        sheet_tab="Arkusz5",
    )
    save_cached_plan("tomek", plan)

    loaded = load_cached_plan("tomek")
    assert loaded is not None
    assert loaded.rows == [["Trening A", "5x5"], ["Squat", "60kg"]]
    assert loaded.fetched_at == 1_700_000_000
    assert loaded.sheet_tab == "Arkusz5"


def test_load_cached_plan_returns_none_for_missing_user(dynamodb_table: Any) -> None:
    from handlers.plan.service import load_cached_plan

    assert load_cached_plan("nonexistent") is None


def test_load_cached_plan_returns_none_for_corrupted_row(dynamodb_table: Any) -> None:
    """Stary cache row z deprecated shape → traktuj jak miss (refetch wymusi clean)."""
    from handlers.plan.service import load_cached_plan

    dynamodb_table.put_item(
        Item={
            "PK": "USER#tomek",
            "SK": "PLAN#current",
            "deprecated_field": "old_shape",
            # missing required: rows, fetched_at, sheet_tab
        }
    )
    assert load_cached_plan("tomek") is None


def test_pk_isolation_two_users_separate_cache(dynamodb_table: Any) -> None:
    from handlers.plan.schemas import CachedPlan
    from handlers.plan.service import load_cached_plan, save_cached_plan

    save_cached_plan(
        "tomek",
        CachedPlan(rows=[["tomek-row"]], fetched_at=1, sheet_tab="Arkusz5"),
    )
    save_cached_plan(
        "weronika",
        CachedPlan(rows=[["weronika-row"]], fetched_at=2, sheet_tab="Arkusz3"),
    )

    tomek = load_cached_plan("tomek")
    weronika = load_cached_plan("weronika")
    assert tomek is not None and tomek.rows == [["tomek-row"]]
    assert weronika is not None and weronika.rows == [["weronika-row"]]
    assert tomek.sheet_tab == "Arkusz5"
    assert weronika.sheet_tab == "Arkusz3"


# ─── Freshness TTL ────────────────────────────────────────────────────────


def test_is_fresh_within_ttl_returns_true() -> None:
    from handlers.plan.schemas import CachedPlan
    from handlers.plan.service import is_fresh

    now = int(time.time())
    plan = CachedPlan(rows=[], fetched_at=now - 300, sheet_tab="Arkusz5")  # 5 min ago
    assert is_fresh(plan, now_epoch=now) is True


def test_is_fresh_past_ttl_returns_false() -> None:
    from handlers.plan.schemas import CachedPlan
    from handlers.plan.service import is_fresh

    now = int(time.time())
    plan = CachedPlan(rows=[], fetched_at=now - 1000, sheet_tab="Arkusz5")  # >15min
    assert is_fresh(plan, now_epoch=now) is False


def test_is_fresh_at_exact_ttl_boundary_returns_false() -> None:
    """now - fetched_at == 900 — nie fresh (strict less-than)."""
    from handlers.plan.schemas import CachedPlan
    from handlers.plan.service import is_fresh

    now = int(time.time())
    plan = CachedPlan(rows=[], fetched_at=now - 900, sheet_tab="Arkusz5")
    assert is_fresh(plan, now_epoch=now) is False
