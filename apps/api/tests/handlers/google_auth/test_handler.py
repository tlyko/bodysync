"""Tests for handlers.google_auth.

Coverage targets per ADR-002:
- happy path (200 + Set-Cookie + DDB PROFILE row)
- missing/invalid body → 400
- invalid Google token → 401
- email spoza allowlisty → 403
- PK isolation: po loginie alice, alice's PROFILE nie miesza się z bob's
- nonce replay protection (sec audit 2026-05-16 P1-1)
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import patch

import jwt
import pytest

# Test nonce ≥16 chars (LoginRequest min_length). Unikalność per test wymagana
# w testach replay-protection — generujemy `uuid4()` lokalnie tam gdzie trzeba.
_DEFAULT_NONCE = "test-nonce-1234567890abcdef"


def _body_with_nonce(
    extra: dict[str, Any] | None = None, nonce: str | None = _DEFAULT_NONCE
) -> dict[str, Any]:
    base: dict[str, Any] = {"id_token": "fake.google.token"}
    if nonce is not None:
        base["nonce"] = nonce
    if extra:
        base.update(extra)
    return base


def _event(body: dict[str, Any] | str | None) -> dict[str, Any]:
    if body is None:
        raw = ""
    elif isinstance(body, str):
        raw = body
    else:
        raw = json.dumps(body)
    return {
        "version": "2.0",
        "routeKey": "POST /api/auth/google",
        "headers": {"content-type": "application/json"},
        "body": raw,
        "isBase64Encoded": False,
    }


class _FakeContext:
    aws_request_id = "test-req-id"


def _patch_google(verified_email: str | None, *, nonce: str = _DEFAULT_NONCE, **extra: Any) -> Any:
    """Patch google.oauth2.id_token.verify_oauth2_token w obrębie testu.

    Zwracana wartość symuluje idinfo dict z `nonce` (Google podpisuje go w
    id_token gdy wstrzykniemy w initialize). Gdy verified_email is None —
    funkcja raise'uje ValueError (jak google-auth dla zepsutego tokenu).
    """

    def fake_verify(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        if verified_email is None:
            raise ValueError("invalid token")
        return {"email": verified_email, "email_verified": True, "nonce": nonce, **extra}

    return patch(
        "handlers.google_auth.service.google_id_token.verify_oauth2_token",
        side_effect=fake_verify,
    )


@pytest.mark.usefixtures("ssm_params")
def test_happy_path_alice(dynamodb_table: Any) -> None:
    from handlers.google_auth import handler as h

    with _patch_google("alice@example.com", name="Alice"):
        result = h.handler(_event(_body_with_nonce()), _FakeContext())

    assert result["statusCode"] == 200
    body = json.loads(result["body"])
    assert body == {"user_id": "alice", "email": "alice@example.com", "name": "Alice"}

    # Set-Cookie via cookies array (HTTP API v2 format)
    assert "cookies" in result
    cookie = result["cookies"][0]
    assert cookie.startswith("bodysync_session=")
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=Lax" in cookie
    assert "Domain=.bodysync.pl" in cookie  # cross-subdomain (api ↔ frontend)

    # JWT odkodowywalne secret'em z SSM, payload ma user_id
    token = cookie.split(";")[0].split("=", 1)[1]
    payload = jwt.decode(
        token,
        "test-jwt-secret-do-not-use-in-prod",
        algorithms=["HS256"],
    )
    assert payload["user_id"] == "alice"
    assert "exp" in payload

    # PROFILE w DDB
    item = dynamodb_table.get_item(Key={"PK": "USER#alice", "SK": "PROFILE"}).get("Item")
    assert item is not None
    assert item["email"] == "alice@example.com"
    assert item["name"] == "Alice"
    assert "last_login" in item


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_400_missing_body() -> None:
    from handlers.google_auth import handler as h

    result = h.handler(_event(None), _FakeContext())
    # Pusty body wpada do {} → Pydantic odrzuca brak id_token.
    assert result["statusCode"] == 400


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_400_invalid_json() -> None:
    from handlers.google_auth import handler as h

    result = h.handler(_event("{not json}"), _FakeContext())
    assert result["statusCode"] == 400


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_400_short_token() -> None:
    from handlers.google_auth import handler as h

    result = h.handler(_event(_body_with_nonce({"id_token": "x"})), _FakeContext())
    assert result["statusCode"] == 400


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_400_missing_nonce() -> None:
    from handlers.google_auth import handler as h

    result = h.handler(_event({"id_token": "fake.google.token"}), _FakeContext())
    assert result["statusCode"] == 400


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_400_short_nonce() -> None:
    from handlers.google_auth import handler as h

    result = h.handler(
        _event({"id_token": "fake.google.token", "nonce": "too-short"}),
        _FakeContext(),
    )
    assert result["statusCode"] == 400


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_400_validation_does_not_leak_user_input() -> None:
    """Reflection guard (sec audit C2): error response NIE może zawierać
    surowego user-supplied value — Pydantic `errors()` zwraca `input`
    field z payloadem, sanityzujemy do `loc + type` only."""
    from handlers.google_auth import handler as h

    # Krótki token (Pydantic min_length=10 odrzuci) z markerem łatwym do
    # wyszukania w response body.
    secret_marker = "AAAA-LEAK"  # 9 chars — pod min_length=10
    result = h.handler(_event({"id_token": secret_marker}), _FakeContext())

    assert result["statusCode"] == 400
    body = json.loads(result["body"])
    assert secret_marker not in json.dumps(body), "user input wyciekł do response"
    # Sanity check że details ma sens dla frontu (info o polu, nie value)
    assert body["details"][0]["loc"] == ["id_token"]
    assert body["details"][0]["type"] == "string_too_short"
    assert "input" not in body["details"][0]


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_401_invalid_google_token() -> None:
    from handlers.google_auth import handler as h

    with _patch_google(verified_email=None):
        result = h.handler(_event(_body_with_nonce()), _FakeContext())
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_401_nonce_mismatch() -> None:
    """id_token podpisany przez Google z innym nonce niż request body.

    Symuluje wykradnięty id_token replay'owany do innego flow (legit user
    request z nonce A, atakujący przekierowuje id_token do swojego flow
    z nonce B). Backend MUSI odrzucić."""
    from handlers.google_auth import handler as h

    with _patch_google("alice@example.com", nonce="nonce-podpisany-w-tokenie"):
        result = h.handler(
            _event({"id_token": "fake.google.token", "nonce": "inny-nonce-w-bodyy"}),
            _FakeContext(),
        )
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_401_nonce_replay() -> None:
    """Drugi request z tym samym nonce → 401 (single-use DDB)."""
    from handlers.google_auth import handler as h

    nonce = "shared-nonce-" + uuid.uuid4().hex
    with _patch_google("alice@example.com", nonce=nonce):
        first = h.handler(_event(_body_with_nonce(nonce=nonce)), _FakeContext())
        assert first["statusCode"] == 200
        # Drugi request — symuluje replay (wykradzione id_token + ten sam nonce).
        second = h.handler(_event(_body_with_nonce(nonce=nonce)), _FakeContext())
        assert second["statusCode"] == 401


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_403_email_not_allowed() -> None:
    from handlers.google_auth import handler as h

    with _patch_google("intruder@example.com"):
        result = h.handler(_event(_body_with_nonce()), _FakeContext())
    assert result["statusCode"] == 403


@pytest.mark.usefixtures("ssm_params")
def test_relogin_preserves_existing_profile_attrs(dynamodb_table: Any) -> None:
    """Re-login MUSI zachować user-managed attrs (kcal_target, diet_check_history,
    body_profile etc). Pre-fix: `put_item` w `service.login` był full overwrite,
    re-login kasował wszystko poza email/name/last_login.

    Critical pre-Weronika onboarding fix — pierwszy raz Weronika by trafiła
    na ten bug bo dla Tomka cookie 30d ukrywał re-login scenariusz.
    """
    from decimal import Decimal

    from handlers.google_auth import handler as h

    # Seed PROFILE alice z user-managed attrs (jakby wcześniej zapisała cele).
    dynamodb_table.put_item(
        Item={
            "PK": "USER#alice",
            "SK": "PROFILE",
            "email": "alice@example.com",
            "name": "Alice",
            "last_login": "2026-04-01T10:00:00+00:00",
            "kcal_target": Decimal("2250"),
            "protein_target_g": Decimal("130"),
            "fat_target_g": Decimal("70"),
            "carbs_target_g": Decimal("275"),
            "height_cm": Decimal("177"),
            "age": Decimal("32"),
            "sex": "male",
            "activity_level": "heavy",
            "goal": "loss",
            "diet_check_history": [
                {
                    "date": "2026-04-15",
                    "skipped": False,
                    "skip_reason": None,
                    "goal_kcal": Decimal("2250"),
                    "kcal_in_avg": Decimal("2050"),
                    "waga_delta_kg": Decimal("-0.4"),
                    "diff_kg": Decimal("-0.04"),
                    "status": "on_track",
                    "narrative": None,
                }
            ],
        }
    )

    with _patch_google("alice@example.com", name="Alice"):
        result = h.handler(
            _event(_body_with_nonce({"id_token": "alice.fake.token"})),
            _FakeContext(),
        )
    assert result["statusCode"] == 200

    profile = dynamodb_table.get_item(Key={"PK": "USER#alice", "SK": "PROFILE"})["Item"]

    # Email/name/last_login zaktualizowane (last_login != stary).
    assert profile["email"] == "alice@example.com"
    assert profile["name"] == "Alice"
    assert profile["last_login"] != "2026-04-01T10:00:00+00:00"

    # User-managed attrs PRESERVED.
    assert int(profile["kcal_target"]) == 2250
    assert int(profile["protein_target_g"]) == 130
    assert int(profile["fat_target_g"]) == 70
    assert int(profile["carbs_target_g"]) == 275
    assert int(profile["height_cm"]) == 177
    assert int(profile["age"]) == 32
    assert profile["sex"] == "male"
    assert profile["activity_level"] == "heavy"
    assert profile["goal"] == "loss"
    assert len(profile["diet_check_history"]) == 1
    assert profile["diet_check_history"][0]["status"] == "on_track"


@pytest.mark.usefixtures("ssm_params")
def test_pk_isolation_two_users(dynamodb_table: Any) -> None:
    """Alice i Bob logują się — każdy ma SWÓJ PROFILE pod swoim PK,
    nie ma cross-write'u."""
    from handlers.google_auth import handler as h

    nonce_a = "alice-nonce-" + uuid.uuid4().hex
    nonce_b = "bob-nonce-" + uuid.uuid4().hex
    with _patch_google("alice@example.com", name="Alice", nonce=nonce_a):
        h.handler(
            _event(_body_with_nonce({"id_token": "alice.fake.token"}, nonce=nonce_a)),
            _FakeContext(),
        )

    with _patch_google("bob@example.com", name="Bob", nonce=nonce_b):
        h.handler(
            _event(_body_with_nonce({"id_token": "bob.fake.token"}, nonce=nonce_b)),
            _FakeContext(),
        )

    alice = dynamodb_table.get_item(Key={"PK": "USER#alice", "SK": "PROFILE"}).get("Item")
    bob = dynamodb_table.get_item(Key={"PK": "USER#bob", "SK": "PROFILE"}).get("Item")

    assert alice is not None and bob is not None
    assert alice["email"] == "alice@example.com"
    assert bob["email"] == "bob@example.com"

    # Query po PK alice nie zwraca bob items.
    alice_items = dynamodb_table.query(
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": "USER#alice"},
    )["Items"]
    assert len(alice_items) == 1
    assert all(i["PK"] == "USER#alice" for i in alice_items)
