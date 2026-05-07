"""Tests for shared.auth (mint_jwt + verify_jwt round-trip)."""

from __future__ import annotations

import time
from typing import Any

import boto3
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


@pytest.mark.usefixtures("dynamodb_table")
def test_jwt_secret_placeholder_fails_fast(monkeypatch: Any) -> None:
    """Sec audit H2 — `mint_jwt` musi fail-fast gdy SSM zwraca PLACEHOLDER
    (defaultowy value z `aws_ssm_parameter` resource w Terraformie). Bez
    tego guard'a każdy minted JWT byłby podpisany stringiem 'PLACEHOLDER'
    i każdy mógłby fałszować user_id."""
    client = boto3.client("ssm", region_name="eu-west-1")
    client.put_parameter(
        Name="/bodysync/jwt/signing_secret",
        Value="PLACEHOLDER",
        Type="SecureString",
    )
    from shared import ssm as _ssm

    _ssm.clear_cache()

    from shared.auth import JwtSecretMisconfiguredError, mint_jwt, verify_jwt

    with pytest.raises(JwtSecretMisconfiguredError):
        mint_jwt("alice")
    with pytest.raises(JwtSecretMisconfiguredError):
        verify_jwt("any.token.here")


@pytest.mark.usefixtures("dynamodb_table")
def test_jwt_secret_too_short_fails_fast(monkeypatch: Any) -> None:
    """Reject sekretów krótszych niż 32 chars — HS256 wymaga ≥256 bitów entropii."""
    client = boto3.client("ssm", region_name="eu-west-1")
    client.put_parameter(
        Name="/bodysync/jwt/signing_secret",
        Value="short",  # 5 chars
        Type="SecureString",
    )
    from shared import ssm as _ssm

    _ssm.clear_cache()

    from shared.auth import JwtSecretMisconfiguredError, mint_jwt

    with pytest.raises(JwtSecretMisconfiguredError):
        mint_jwt("alice")
