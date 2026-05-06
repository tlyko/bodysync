"""Tests for shared.auth (mint_jwt + verify_jwt round-trip)."""

from __future__ import annotations

import time

import pytest


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_mint_then_verify_round_trip() -> None:
    from shared.auth import mint_jwt, verify_jwt

    token = mint_jwt("alice")
    payload = verify_jwt(token)
    assert payload["user_id"] == "alice"
    assert payload["exp"] > int(time.time())


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_tampered_signature_rejected() -> None:
    from shared.auth import AuthError, mint_jwt, verify_jwt

    token = mint_jwt("alice") + "tampered"
    with pytest.raises(AuthError):
        verify_jwt(token)


@pytest.mark.usefixtures("ssm_params", "dynamodb_table")
def test_garbage_token_rejected() -> None:
    from shared.auth import AuthError, verify_jwt

    with pytest.raises(AuthError):
        verify_jwt("not.a.jwt")
