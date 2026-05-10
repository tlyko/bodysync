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
    path: str = "/api/profile/targets",
) -> dict[str, Any]:
    cookies: list[str] = [cookie] if cookie else []
    return {
        "version": "2.0",
        "routeKey": f"{method} {path}",
        "rawPath": path,
        "requestContext": {"http": {"method": method}},
        "headers": {"content-type": "application/json"},
        "cookies": cookies,
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
    }


def _seed_weight(table: Any, user_id: str, *, date_iso: str, kg: float) -> None:
    """Helper — wpisz BIOMETRY weight item dla `get_latest_weight_kg` lookup."""
    from decimal import Decimal

    table.put_item(
        Item={
            "PK": f"USER#{user_id}",
            "SK": f"BIOMETRY#{date_iso}#weight",
            "kg": Decimal(str(kg)),
        }
    )


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
        "body_profile": None,
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
        "body_profile": None,
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


# ─── body_profile w GET / PUT ──────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_params")
def test_get_returns_body_profile_when_set(dynamodb_table: Any) -> None:
    from handlers.profile_targets import handler as h

    _seed_profile(
        dynamodb_table,
        "tomek",
        kcal_target=2400,
        protein_target_g=160,
        fat_target_g=80,
        carbs_target_g=260,
        height_cm=180,
        age=32,
        sex="male",
        activity_level="moderate",
        goal="maintain",
    )

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(_event("GET", cookie), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["body_profile"] == {
        "height_cm": 180,
        "age": 32,
        "sex": "male",
        "activity_level": "moderate",
        "goal": "maintain",
    }


@pytest.mark.usefixtures("ssm_params")
def test_put_persists_body_profile(dynamodb_table: Any) -> None:
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
                "body_profile": {
                    "height_cm": 180,
                    "age": 32,
                    "sex": "male",
                    "activity_level": "moderate",
                    "goal": "maintain",
                },
            },
        ),
        _FakeContext(),
    )

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["body_profile"]["height_cm"] == 180

    # Verify persistence + email zachowany
    raw = dynamodb_table.get_item(Key={"PK": "USER#tomek", "SK": "PROFILE"})["Item"]
    assert raw["height_cm"] == 180
    assert raw["activity_level"] == "moderate"
    assert raw["email"] == "tomek@example.com"


# ─── POST /api/profile/calculate-tdee ──────────────────────────────────────


@pytest.mark.usefixtures("ssm_params")
def test_calculate_tdee_happy_with_payload(dynamodb_table: Any) -> None:
    from handlers.profile_targets import handler as h

    _seed_profile(dynamodb_table, "tomek")
    _seed_weight(dynamodb_table, "tomek", date_iso="2026-05-09", kg=82.0)

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(
        _event(
            "POST",
            cookie,
            path="/api/profile/calculate-tdee",
            body={
                "body_profile": {
                    "height_cm": 180,
                    "age": 32,
                    "sex": "male",
                    "activity_level": "moderate",
                    "goal": "maintain",
                },
            },
        ),
        _FakeContext(),
    )

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    # BMR = 10*82 + 6.25*180 - 5*32 + 5 = 820 + 1125 - 160 + 5 = 1790
    assert body["bmr"] == 1790
    # TDEE = 1790 * 1.55 = 2774.5 → round 2774 lub 2775 (Python round half-even)
    assert body["tdee_maintenance"] in (2774, 2775)
    # Goal maintain: target_kcal = round(tdee/10)*10
    assert body["target_kcal"] in (2770, 2780)
    # Macros: protein 1.8 * 82 = 147.6 → 150g; fat 0.9 * 82 = 73.8 → 75g
    assert body["target_protein_g"] == 150
    assert body["target_fat_g"] == 75
    # Carbs: rest of kcal / 4
    assert body["target_carbs_g"] > 0
    assert body["weight_kg_used"] == 82.0


@pytest.mark.usefixtures("ssm_params")
def test_calculate_tdee_uses_stored_body_profile_when_omitted(dynamodb_table: Any) -> None:
    from handlers.profile_targets import handler as h

    _seed_profile(
        dynamodb_table,
        "tomek",
        height_cm=180,
        age=32,
        sex="male",
        activity_level="light",
        goal="loss",
    )
    _seed_weight(dynamodb_table, "tomek", date_iso="2026-05-09", kg=82.0)

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(
        _event("POST", cookie, path="/api/profile/calculate-tdee", body={}),
        _FakeContext(),
    )

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    # TDEE = 1790 * 1.375 = 2461.25; goal loss = -500; target ~1960
    assert 1950 <= body["target_kcal"] <= 1970


@pytest.mark.usefixtures("ssm_params")
def test_calculate_tdee_400_no_body_profile_anywhere(dynamodb_table: Any) -> None:
    from handlers.profile_targets import handler as h

    _seed_profile(dynamodb_table, "tomek")  # bez body profile attrów
    _seed_weight(dynamodb_table, "tomek", date_iso="2026-05-09", kg=82.0)

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(
        _event("POST", cookie, path="/api/profile/calculate-tdee", body={}),
        _FakeContext(),
    )

    assert result["statusCode"] == 400
    body = json.loads(result["body"])
    assert body["error"] == "body_profile_required"


@pytest.mark.usefixtures("ssm_params")
def test_calculate_tdee_400_no_weight_in_biometry(dynamodb_table: Any) -> None:
    from handlers.profile_targets import handler as h

    _seed_profile(
        dynamodb_table,
        "tomek",
        height_cm=180,
        age=32,
        sex="male",
        activity_level="moderate",
        goal="maintain",
    )
    # NIE seed waga

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(
        _event("POST", cookie, path="/api/profile/calculate-tdee", body={}),
        _FakeContext(),
    )

    assert result["statusCode"] == 400
    body = json.loads(result["body"])
    assert body["error"] == "weight_not_found"


@pytest.mark.usefixtures("ssm_params")
def test_calculate_tdee_uses_payload_weight_override(dynamodb_table: Any) -> None:
    from handlers.profile_targets import handler as h

    _seed_profile(dynamodb_table, "tomek")
    _seed_weight(dynamodb_table, "tomek", date_iso="2026-05-09", kg=82.0)

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    result = h.handler(
        _event(
            "POST",
            cookie,
            path="/api/profile/calculate-tdee",
            body={
                "body_profile": {
                    "height_cm": 180,
                    "age": 32,
                    "sex": "male",
                    "activity_level": "moderate",
                    "goal": "maintain",
                },
                "weight_kg": 75.0,
            },
        ),
        _FakeContext(),
    )

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body["weight_kg_used"] == 75.0


@pytest.mark.usefixtures("ssm_params")
def test_calculate_tdee_400_invalid_body_profile(dynamodb_table: Any) -> None:
    from handlers.profile_targets import handler as h

    _seed_profile(dynamodb_table, "tomek")
    _seed_weight(dynamodb_table, "tomek", date_iso="2026-05-09", kg=82.0)

    cookie = f"bodysync_session={_mint_test_jwt('tomek')}"
    # height 99 < min 140
    result = h.handler(
        _event(
            "POST",
            cookie,
            path="/api/profile/calculate-tdee",
            body={
                "body_profile": {
                    "height_cm": 99,
                    "age": 32,
                    "sex": "male",
                    "activity_level": "moderate",
                    "goal": "maintain",
                },
            },
        ),
        _FakeContext(),
    )

    assert result["statusCode"] == 400


@pytest.mark.usefixtures("ssm_params")
def test_calculate_tdee_female_sex_offset(dynamodb_table: Any) -> None:
    """BMR formula offset: -161 dla female (vs +5 dla male).
    Differential = 166 kcal w BMR przy tych samych innych parametrach.
    """
    from handlers.profile_targets import handler as h

    _seed_profile(dynamodb_table, "weronika")
    _seed_weight(dynamodb_table, "weronika", date_iso="2026-05-09", kg=60.0)

    cookie = f"bodysync_session={_mint_test_jwt('weronika')}"
    result = h.handler(
        _event(
            "POST",
            cookie,
            path="/api/profile/calculate-tdee",
            body={
                "body_profile": {
                    "height_cm": 168,
                    "age": 28,
                    "sex": "female",
                    "activity_level": "moderate",
                    "goal": "maintain",
                },
            },
        ),
        _FakeContext(),
    )

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    # BMR = 10*60 + 6.25*168 - 5*28 + (-161) = 600 + 1050 - 140 - 161 = 1349
    assert body["bmr"] == 1349
    # TDEE = 1349 * 1.55 = 2090.95 → 2091
    assert body["tdee_maintenance"] == 2091


@pytest.mark.usefixtures("ssm_params")
def test_calculate_tdee_pk_isolation_no_cross_user_weight(dynamodb_table: Any) -> None:
    """`get_latest_weight_kg` queryuje PK=USER#{user_id} — waga user_a NIE
    leakuje do calculate-tdee user_b. Critical PK isolation invariant.
    """
    from handlers.profile_targets import handler as h

    _seed_profile(dynamodb_table, "tomek")
    _seed_profile(dynamodb_table, "weronika")
    _seed_weight(dynamodb_table, "tomek", date_iso="2026-05-09", kg=82.0)
    # Weronika nie ma waga w DDB

    cookie = f"bodysync_session={_mint_test_jwt('weronika')}"
    result = h.handler(
        _event(
            "POST",
            cookie,
            path="/api/profile/calculate-tdee",
            body={
                "body_profile": {
                    "height_cm": 168,
                    "age": 28,
                    "sex": "female",
                    "activity_level": "moderate",
                    "goal": "maintain",
                },
            },
        ),
        _FakeContext(),
    )

    # Weronika dostaje 400 weight_not_found (NIE leak Tomka 82.0 kg)
    assert result["statusCode"] == 400
    body = json.loads(result["body"])
    assert body["error"] == "weight_not_found"
