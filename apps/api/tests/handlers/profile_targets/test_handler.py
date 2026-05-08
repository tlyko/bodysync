"""Tests dla handlers.profile_targets — GET + PUT /api/profile/targets."""

from __future__ import annotations

import json
from typing import Any

import pytest


def _event(
    method: str,
    cookie: str | None,
    *,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cookies: list[str] = [cookie] if cookie else []
    return {
        "version": "2.0",
        "routeKey": f"{method} /api/profile/targets",
        "rawPath": "/api/profile/targets",
        "requestContext": {"http": {"method": method}},
        "headers": {"content-type": "application/json"},
        "cookies": cookies,
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
    }


class _FakeContext:
    aws_request_id = "test-req-id"


def _mint_test_jwt(user_id: str) -> str:
    from shared.auth import mint_jwt

    return mint_jwt(user_id)


def _seed_profile(table: Any, user_id: str, **extra_attrs: Any) -> None:
    item = {
        "PK": f"USER#{user_id}",
        "SK": "PROFILE",
        "email": f"{user_id}@example.com",
        "name": user_id,
        **extra_attrs,
    }
    table.put_item(Item=item)


# ─── GET ───────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params")
def test_get_returns_defaults_when_targets_unset(dynamodb_table: Any) -> None:
    from handlers.profile_targets import handler as h

    _seed_profile(dynamodb_table, "tomek")  # bez kcal_target etc.

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_event("GET", cookie), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body == {
        "kcal_target": 2000,
        "protein_target_g": 130,
        "fat_target_g": 70,
        "carbs_target_g": 200,
        "is_default": True,
    }


@pytest.mark.usefixtures("ssm_params")
def test_get_returns_owner_values_when_set(dynamodb_table: Any) -> None:
    from handlers.profile_targets import handler as h

    _seed_profile(
        dynamodb_table,
        "tomek",
        kcal_target=2400,
        protein_target_g=160,
        fat_target_g=80,
        carbs_target_g=260,
    )

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_event("GET", cookie), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body == {
        "kcal_target": 2400,
        "protein_target_g": 160,
        "fat_target_g": 80,
        "carbs_target_g": 260,
        "is_default": False,
    }


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_get_401_no_cookie() -> None:
    from handlers.profile_targets import handler as h

    result = h.handler(_event("GET", cookie=None), _FakeContext())
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_get_404_profile_missing() -> None:
    from handlers.profile_targets import handler as h

    cookie = f"bodysync_session={_mint_test_jwt('ghost')}"
    result = h.handler(_event("GET", cookie), _FakeContext())
    assert result["statusCode"] == 404


# ─── PUT ───────────────────────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params")
def test_put_happy_persists_targets(dynamodb_table: Any) -> None:
    from handlers.profile_targets import handler as h

    _seed_profile(dynamodb_table, "tomek")

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(
        _event(
            "PUT",
            cookie,
            body={
                "kcal_target": 2400,
                "protein_target_g": 160,
                "fat_target_g": 80,
                "carbs_target_g": 260,
            },
        ),
        _FakeContext(),
    )

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["is_default"] is False
    assert body["kcal_target"] == 2400

    # Verify persistence: re-fetch via GET
    follow = h.handler(_event("GET", cookie), _FakeContext())
    assert json.loads(follow["body"])["kcal_target"] == 2400

    # Verify zachowanie email/name (merge nie nadpisał)
    raw = dynamodb_table.get_item(Key={"PK": "USER#tomek", "SK": "PROFILE"})["Item"]
    assert raw["email"] == "tomek@example.com"
    assert raw["name"] == "tomek"


@pytest.mark.usefixtures("ssm_params")
def test_put_400_kcal_below_range(dynamodb_table: Any) -> None:
    from handlers.profile_targets import handler as h

    _seed_profile(dynamodb_table, "tomek")
    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"

    result = h.handler(
        _event(
            "PUT",
            cookie,
            body={
                "kcal_target": 500,  # < 1000 floor
                "protein_target_g": 130,
                "fat_target_g": 70,
                "carbs_target_g": 200,
            },
        ),
        _FakeContext(),
    )
    assert result["statusCode"] == 400


@pytest.mark.usefixtures("ssm_params")
def test_put_400_missing_field(dynamodb_table: Any) -> None:
    from handlers.profile_targets import handler as h

    _seed_profile(dynamodb_table, "tomek")
    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"

    result = h.handler(
        _event(
            "PUT",
            cookie,
            body={"kcal_target": 2400, "protein_target_g": 160},  # missing fat/carbs
        ),
        _FakeContext(),
    )
    assert result["statusCode"] == 400


@pytest.mark.usefixtures("ssm_params")
def test_put_400_invalid_json(dynamodb_table: Any) -> None:
    from handlers.profile_targets import handler as h

    _seed_profile(dynamodb_table, "tomek")
    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"

    bad = _event("PUT", cookie)
    bad["body"] = "{not json"
    result = h.handler(bad, _FakeContext())
    assert result["statusCode"] == 400


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_put_401_no_cookie() -> None:
    from handlers.profile_targets import handler as h

    result = h.handler(
        _event(
            "PUT",
            cookie=None,
            body={
                "kcal_target": 2400,
                "protein_target_g": 160,
                "fat_target_g": 80,
                "carbs_target_g": 260,
            },
        ),
        _FakeContext(),
    )
    assert result["statusCode"] == 401


# ─── method dispatch ───────────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params")
def test_unsupported_method_405(dynamodb_table: Any) -> None:
    from handlers.profile_targets import handler as h

    _seed_profile(dynamodb_table, "tomek")
    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"

    result = h.handler(_event("DELETE", cookie), _FakeContext())
    assert result["statusCode"] == 405
