"""Tests for handlers.google_auth.

Coverage targets per ADR-002:
- happy path (200 + Set-Cookie + DDB PROFILE row)
- missing/invalid body → 400
- invalid Google token → 401
- email spoza allowlisty → 403
- PK isolation: po loginie alice, alice's PROFILE nie miesza się z bob's
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import jwt
import pytest


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


def _patch_google(verified_email: str | None, **extra: Any) -> Any:
    """Patch google.oauth2.id_token.verify_oauth2_token w obrębie testu.

    Zwracana wartość symuluje idinfo dict; gdy verified_email is None — funkcja
    raise'uje ValueError (jak google-auth dla zepsutego tokenu).
    """

    def fake_verify(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        if verified_email is None:
            raise ValueError("invalid token")
        return {"email": verified_email, "email_verified": True, **extra}

    return patch(
        "handlers.google_auth.service.google_id_token.verify_oauth2_token",
        side_effect=fake_verify,
    )


@pytest.mark.usefixtures("ssm_params")
def test_happy_path_alice(dynamodb_table: Any) -> None:
    from handlers.google_auth import handler as h

    with _patch_google("alice@example.com", name="Alice"):
        result = h.handler(_event({"id_token": "fake.google.token"}), _FakeContext())

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

    result = h.handler(_event({"id_token": "x"}), _FakeContext())
    assert result["statusCode"] == 400


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_401_invalid_google_token() -> None:
    from handlers.google_auth import handler as h

    with _patch_google(verified_email=None):
        result = h.handler(_event({"id_token": "garbage.token.here"}), _FakeContext())
    assert result["statusCode"] == 401


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_403_email_not_allowed() -> None:
    from handlers.google_auth import handler as h

    with _patch_google("intruder@example.com"):
        result = h.handler(_event({"id_token": "fake.google.token"}), _FakeContext())
    assert result["statusCode"] == 403


@pytest.mark.usefixtures("ssm_params")
def test_pk_isolation_two_users(dynamodb_table: Any) -> None:
    """Alice i Bob logują się — każdy ma SWÓJ PROFILE pod swoim PK,
    nie ma cross-write'u."""
    from handlers.google_auth import handler as h

    with _patch_google("alice@example.com", name="Alice"):
        h.handler(_event({"id_token": "alice.fake.token"}), _FakeContext())

    with _patch_google("bob@example.com", name="Bob"):
        h.handler(_event({"id_token": "bob.fake.token"}), _FakeContext())

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
