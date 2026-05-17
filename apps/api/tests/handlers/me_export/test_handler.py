"""Tests dla handlers.me_export — GET /api/me/export (GDPR Art. 20 export).

Pattern z `measurements/test_handler.py` — JWT cookie + CSRF guard, moto DDB
fixture, fake context. PK isolation regression z parą user_a + user_b
samplem.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

_CSRF_TEST_TOKEN = "test-csrf-token-deterministic"


def _event(
    cookie: str | None,
    *,
    csrf: bool = True,
) -> dict[str, Any]:
    cookies: list[str] = [cookie] if cookie else []
    headers: dict[str, str] = {}
    if csrf:
        cookies.append(f"bodysync_csrf={_CSRF_TEST_TOKEN}")
        headers["x-csrf-token"] = _CSRF_TEST_TOKEN
    return {
        "version": "2.0",
        "routeKey": "GET /api/me/export",
        "rawPath": "/api/me/export",
        "requestContext": {"http": {"method": "GET"}},
        "headers": headers,
        "cookies": cookies,
        "body": None,
        "isBase64Encoded": False,
    }


class _FakeContext:
    aws_request_id = "test-req-id"


def _mint_test_jwt(user_id: str) -> str:
    from shared.auth import mint_jwt

    return mint_jwt(user_id)


def _seed_user_rows(table: Any, user_id: str) -> None:
    """Pre-seed sample rows reprezentatywne dla typowego usera."""
    pk = f"USER#{user_id}"
    table.put_item(Item={"PK": pk, "SK": "PROFILE", "email": f"{user_id}@example.com"})
    table.put_item(
        Item={
            "PK": pk,
            "SK": "BIOMETRY#2026-05-01#weight",
            "kg": Decimal("82.5"),
            "source": "hae",
        }
    )
    table.put_item(
        Item={
            "PK": pk,
            "SK": "BIOMETRY#2026-05-02#hrv",
            "ms": Decimal("48"),
            "source": "hae",
        }
    )
    table.put_item(
        Item={
            "PK": pk,
            "SK": "ACTIVITY#123456",
            "sport_type": "Run",
            "distance_km": Decimal("5.2"),
        }
    )
    table.put_item(
        Item={
            "PK": pk,
            "SK": "PLAN#current",
            "weeks": ["Trening A", "Trening B"],
        }
    )


# ─── Auth ─────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_missing_cookie_returns_401() -> None:
    from handlers.me_export import handler as h

    result = h.handle(_event(None), _FakeContext())
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_invalid_jwt_returns_401() -> None:
    from handlers.me_export import handler as h

    result = h.handle(_event("bodysync_session=not-a-jwt"), _FakeContext())
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_missing_csrf_returns_403() -> None:
    from handlers.me_export import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(_event(cookie, csrf=False), _FakeContext())
    assert result["statusCode"] == 403


# ─── Happy path ────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params")
def test_happy_returns_full_dump_with_manifest(dynamodb_table: Any) -> None:
    from handlers.me_export import handler as h

    _seed_user_rows(dynamodb_table, "tomek")
    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"

    result = h.handle(_event(cookie), _FakeContext())

    assert result["statusCode"] == 200
    headers = result["headers"]
    assert headers["Content-Type"] == "application/json"
    assert headers["Content-Disposition"].startswith('attachment; filename="bodysync-export-tomek-')
    assert headers["Content-Disposition"].endswith('.json"')

    body = json.loads(result["body"])
    manifest = body["manifest"]
    assert manifest["user_id"] == "tomek"
    assert manifest["row_count"] == 5
    assert manifest["types"] == {
        "ACTIVITY": 1,
        "BIOMETRY": 2,
        "PLAN": 1,
        "PROFILE": 1,
    }
    assert "generated_at" in manifest

    # Rows zachowują wartości + native num types (NIE Decimal stringi).
    by_sk = {row["SK"]: row for row in body["rows"]}
    assert by_sk["BIOMETRY#2026-05-01#weight"]["kg"] == 82.5
    assert by_sk["BIOMETRY#2026-05-02#hrv"]["ms"] == 48  # integral → int
    assert isinstance(by_sk["BIOMETRY#2026-05-02#hrv"]["ms"], int)
    assert by_sk["PROFILE"]["email"] == "tomek@example.com"


# ─── PK isolation regression ──────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params")
def test_pk_isolation_user_a_cannot_see_user_b(dynamodb_table: Any) -> None:
    """Dwóch userów w tabeli — eksport tomka NIE zawiera rows weroniki."""
    from handlers.me_export import handler as h

    _seed_user_rows(dynamodb_table, "tomek")
    _seed_user_rows(dynamodb_table, "weronika")

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(_event(cookie), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["manifest"]["user_id"] == "tomek"
    assert body["manifest"]["row_count"] == 5
    # Żaden row nie powinien mieć email weroniki ani jej PK leakage.
    for row in body["rows"]:
        assert "weronika" not in json.dumps(row, default=str)


# ─── Empty user ───────────────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_empty_user_returns_zero_rows() -> None:
    """Świeży user bez żadnych rows — 200 z pustym dump'em + manifestem."""
    from handlers.me_export import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('alice')}"
    result = h.handle(_event(cookie), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["manifest"]["row_count"] == 0
    assert body["manifest"]["types"] == {}
    assert body["rows"] == []


# ─── Pagination ────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params")
def test_query_all_paginates_full_partition(dynamodb_table: Any) -> None:
    """Sprawdzenie że `query_all_by_pk` iteruje przez LastEvaluatedKey.

    Moto domyślnie zwraca wszystko w jednym page, ale `query_all_by_pk`
    wywołuje `_table.query` w pętli — patchujemy żeby zwrócić 2 strony i
    sprawdzić że scal'amy wyniki.
    """
    from shared import dynamo

    pk = "USER#tomek"
    # 30 rows BIOMETRY — wystarczy żeby manifest pokazał poprawny count.
    for i in range(30):
        dynamodb_table.put_item(
            Item={
                "PK": pk,
                "SK": f"BIOMETRY#2026-05-{i + 1:02d}#weight",
                "kg": Decimal(f"80.{i}"),
            }
        )

    rows = dynamo.query_all_by_pk(pk)
    assert len(rows) == 30
    assert all(r["PK"] == pk for r in rows)
