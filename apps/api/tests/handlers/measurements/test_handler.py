"""Tests dla handlers.measurements — POST /api/measurements.

Sprint 12 — manual body tape measurements (talia/biodra/klatka/biceps/udo).
Mirror layout testów `profile_targets/test_handler.py`.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError

_CSRF_TEST_TOKEN = "test-csrf-token-deterministic"


def _event(
    cookie: str | None,
    *,
    body: dict[str, Any] | None = None,
    raw_body: str | None = None,
    csrf: bool = True,
) -> dict[str, Any]:
    cookies: list[str] = [cookie] if cookie else []
    headers: dict[str, str] = {"content-type": "application/json"}
    if csrf:
        cookies.append(f"bodysync_csrf={_CSRF_TEST_TOKEN}")
        headers["x-csrf-token"] = _CSRF_TEST_TOKEN
    if raw_body is not None:
        body_str: str | None = raw_body
    else:
        body_str = json.dumps(body) if body is not None else None
    return {
        "version": "2.0",
        "routeKey": "POST /api/measurements",
        "rawPath": "/api/measurements",
        "requestContext": {"http": {"method": "POST"}},
        "headers": headers,
        "cookies": cookies,
        "body": body_str,
        "isBase64Encoded": False,
    }


class _FakeContext:
    aws_request_id = "test-req-id"


def _mint_test_jwt(user_id: str) -> str:
    from shared.auth import mint_jwt

    return mint_jwt(user_id)


# ─── CSRF guard (sec audit 2026-05-16 P1-4) ───────────────────────────────


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_post_without_csrf_returns_403() -> None:
    from handlers.measurements import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(
        _event(cookie, body={"date": "2026-05-17", "waist": 80.0}, csrf=False),
        _FakeContext(),
    )
    assert result["statusCode"] == 403


# ─── Happy path ────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params")
def test_post_happy_persists_five_metrics(dynamodb_table: Any) -> None:
    """5 obwodów wpisane → 200 + 5 DDB rows + saved list w response."""
    from handlers.measurements import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(
        _event(
            cookie,
            body={
                "date": "2026-05-14",
                "waist_cm": 85.5,
                "hips_cm": 98.0,
                "chest_cm": 102.0,
                "biceps_cm": 35.5,
                "thigh_cm": 58.0,
            },
        ),
        _FakeContext(),
    )

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["date"] == "2026-05-14"
    assert sorted(body["saved"]) == ["biceps", "chest", "hips", "thigh", "waist"]

    # DDB rows zapisane pod USER#tomek z prawidłowym SK format.
    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :skp)",
        ExpressionAttributeValues={
            ":pk": "USER#tomek",
            ":skp": "BIOMETRY#2026-05-14#",
        },
    )["Items"]
    assert len(items) == 5

    # Każdy item ma poprawne attrs.
    waist_item = next(it for it in items if "#waist#" in it["SK"])
    assert waist_item["SK"] == "BIOMETRY#2026-05-14#waist#manual"
    assert waist_item["cm"] == Decimal("85.5")
    assert waist_item["source"] == "manual"
    assert "recorded_at" in waist_item


@pytest.mark.usefixtures("ssm_params")
def test_post_partial_save_skips_null_metrics(dynamodb_table: Any) -> None:
    """Tylko `waist` + `biceps` w request → 2 DDB rows, pozostałe NIE
    zapisane (None Pydantic optional)."""
    from handlers.measurements import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(
        _event(
            cookie,
            body={
                "date": "2026-05-14",
                "waist_cm": 85.5,
                "biceps_cm": 35.5,
                # hips/chest/thigh pominięte
            },
        ),
        _FakeContext(),
    )

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert sorted(body["saved"]) == ["biceps", "waist"]

    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :skp)",
        ExpressionAttributeValues={
            ":pk": "USER#tomek",
            ":skp": "BIOMETRY#2026-05-14#",
        },
    )["Items"]
    assert len(items) == 2
    sks = sorted(it["SK"] for it in items)
    assert sks == [
        "BIOMETRY#2026-05-14#biceps#manual",
        "BIOMETRY#2026-05-14#waist#manual",
    ]


# ─── Validation errors (422) ───────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_post_422_all_metrics_null() -> None:
    """Request bez ŻADNEJ metryki → 422 (model_validator)."""
    from handlers.measurements import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(
        _event(cookie, body={"date": "2026-05-14"}),
        _FakeContext(),
    )

    assert result["statusCode"] == 422
    body = json.loads(result["body"])
    assert body["error"] == "validation_failed"
    assert isinstance(body["fields"], list)


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_post_422_invalid_date_format() -> None:
    """`2026-5-14` (bez padding) → regex reject → 422."""
    from handlers.measurements import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(
        _event(cookie, body={"date": "2026-5-14", "waist_cm": 85.5}),
        _FakeContext(),
    )

    assert result["statusCode"] == 422


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_post_422_value_out_of_range() -> None:
    """Negative cm → Pydantic gt=0 reject → 422."""
    from handlers.measurements import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(
        _event(cookie, body={"date": "2026-05-14", "waist_cm": -5.0}),
        _FakeContext(),
    )

    assert result["statusCode"] == 422


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_post_422_value_above_max() -> None:
    """>= 500 cm → lt=500 reject → 422."""
    from handlers.measurements import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(
        _event(cookie, body={"date": "2026-05-14", "thigh_cm": 999.0}),
        _FakeContext(),
    )

    assert result["statusCode"] == 422


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_post_422_invalid_json_body() -> None:
    """Niepoprawny JSON → 422."""
    from handlers.measurements import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(
        _event(cookie, raw_body="{not json"),
        _FakeContext(),
    )

    assert result["statusCode"] == 422


# ─── Auth (401) ────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_post_401_no_cookie() -> None:
    from handlers.measurements import handler as h

    result = h.handle(
        _event(cookie=None, body={"date": "2026-05-14", "waist_cm": 85.5}),
        _FakeContext(),
    )

    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_post_401_invalid_jwt() -> None:
    from handlers.measurements import handler as h

    result = h.handle(
        _event(
            cookie="bodysync_session=garbage.jwt.token",
            body={"date": "2026-05-14", "waist_cm": 85.5},
        ),
        _FakeContext(),
    )

    assert result["statusCode"] == 401


# ─── PK isolation ──────────────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params")
def test_post_pk_isolation_uses_jwt_user_id_not_body(dynamodb_table: Any) -> None:
    """Critical CLAUDE.md "Reguła PK isolation": handler MUSI scope'ować
    DDB write pod USER#{user_id z JWT}, NIGDY z body. Test sprawdza że
    nawet gdyby body miało `user_id`/`PK` field, write idzie pod JWT
    użytkownika (weronika), NIE pod user z body (tomek).
    """
    from handlers.measurements import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('weronika')}"
    result = h.handle(
        _event(
            cookie,
            body={
                "date": "2026-05-14",
                "waist_cm": 72.0,
                # Próba "podszycia się" — schemas Pydantic ignoruje extra
                # fields, ale i tak weryfikujemy invariant.
                "user_id": "tomek",
                "PK": "USER#tomek",
            },
        ),
        _FakeContext(),
    )

    assert result["statusCode"] == 200

    # Item zapisany pod weronika, NIE tomek.
    weronika_items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :skp)",
        ExpressionAttributeValues={
            ":pk": "USER#weronika",
            ":skp": "BIOMETRY#2026-05-14#",
        },
    )["Items"]
    assert len(weronika_items) == 1
    assert weronika_items[0]["cm"] == Decimal("72.0")

    tomek_items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :skp)",
        ExpressionAttributeValues={
            ":pk": "USER#tomek",
            ":skp": "BIOMETRY#2026-05-14#",
        },
    )["Items"]
    assert len(tomek_items) == 0


# ─── DDB write failure (500) ───────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_post_500_when_ddb_write_fails() -> None:
    """ClientError z boto3 → 500 internal."""
    from handlers.measurements import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"

    fake_error = ClientError(
        {"Error": {"Code": "InternalServerError", "Message": "Boom"}},
        "PutItem",
    )

    with patch("handlers.measurements.handler.save_measurements", side_effect=fake_error):
        result = h.handle(
            _event(cookie, body={"date": "2026-05-14", "waist_cm": 85.5}),
            _FakeContext(),
        )

    assert result["statusCode"] == 500
    body = json.loads(result["body"])
    assert body["error"] == "internal"


# ─── Manual nutrition entry (post-Recovery sprint) ─────────────────────────


@pytest.mark.usefixtures("ssm_params")
def test_post_nutrition_persists_kcal_and_macros(dynamodb_table: Any) -> None:
    """kcal_in + P/F/C → 4 DDB rows z properly mapowanym attr per metric."""
    from handlers.measurements import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(
        _event(
            cookie,
            body={
                "date": "2026-05-17",
                "kcal_in": 2200,
                "protein_g": 150,
                "fat_g": 80,
                "carbs_g": 250,
            },
        ),
        _FakeContext(),
    )

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert sorted(body["saved"]) == ["carbs", "fat", "kcal_in", "protein"]

    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :skp)",
        ExpressionAttributeValues={
            ":pk": "USER#tomek",
            ":skp": "BIOMETRY#2026-05-17#",
        },
    )["Items"]
    assert len(items) == 4

    by_sk = {it["SK"]: it for it in items}
    # kcal_in → attrs has `kcal` (mirror HAE shape).
    kcal_item = by_sk["BIOMETRY#2026-05-17#kcal_in#manual"]
    assert kcal_item["kcal"] == Decimal("2200")
    assert kcal_item["source"] == "manual"
    # Makro → attrs has `g`.
    protein_item = by_sk["BIOMETRY#2026-05-17#protein#manual"]
    assert protein_item["g"] == Decimal("150")
    assert protein_item["source"] == "manual"
    fat_item = by_sk["BIOMETRY#2026-05-17#fat#manual"]
    assert fat_item["g"] == Decimal("80")
    carbs_item = by_sk["BIOMETRY#2026-05-17#carbs#manual"]
    assert carbs_item["g"] == Decimal("250")


@pytest.mark.usefixtures("ssm_params")
def test_post_mixed_body_and_nutrition(dynamodb_table: Any) -> None:
    """Jednym requestem waist (cm) + kcal_in (kcal) — różne attr per metric."""
    from handlers.measurements import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(
        _event(
            cookie,
            body={"date": "2026-05-17", "waist_cm": 85.5, "kcal_in": 2200},
        ),
        _FakeContext(),
    )

    assert result["statusCode"] == 200
    items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :skp)",
        ExpressionAttributeValues={
            ":pk": "USER#tomek",
            ":skp": "BIOMETRY#2026-05-17#",
        },
    )["Items"]
    assert len(items) == 2
    by_sk = {it["SK"]: it for it in items}
    assert by_sk["BIOMETRY#2026-05-17#waist#manual"]["cm"] == Decimal("85.5")
    assert by_sk["BIOMETRY#2026-05-17#kcal_in#manual"]["kcal"] == Decimal("2200")


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_post_422_kcal_in_too_large() -> None:
    """kcal_in > 10000 (top guard chroniący przed typo 25000 zamiast 2500)."""
    from handlers.measurements import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(
        _event(cookie, body={"date": "2026-05-17", "kcal_in": 25000}),
        _FakeContext(),
    )
    assert result["statusCode"] == 422


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_post_422_negative_protein() -> None:
    """protein_g ≤ 0 → 422 (Field gt=0)."""
    from handlers.measurements import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handle(
        _event(cookie, body={"date": "2026-05-17", "protein_g": -10}),
        _FakeContext(),
    )
    assert result["statusCode"] == 422
