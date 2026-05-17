"""SSM Parameter Store reads with module-level cache.

Cold start cost: ~30-100ms per parameter. Warm Lambda re-uses module globals,
so cache survives across invocations until container freeze.
"""

from __future__ import annotations

from typing import Any

import boto3

_client: Any = None  # boto3 SSM client; lazy init dla testów moto + cold-start
_cache: dict[str, str] = {}


def _get_client() -> Any:
    """Lazy boto3 client — chronik pre-moto-context init w testach. Lambda
    cold-start nadal raz inicjalizuje per container (jeden API call differ).
    """
    global _client
    if _client is None:
        _client = boto3.client("ssm")
    return _client


def get_param(name: str, *, decrypt: bool = True) -> str:
    """Fetch SSM parameter, cached for the lifetime of the Lambda container.

    Use `decrypt=True` for SecureString. String/StringList tolerate it too.
    """
    cached = _cache.get(name)
    if cached is not None:
        return cached
    resp = _get_client().get_parameter(Name=name, WithDecryption=decrypt)
    value: str = resp["Parameter"]["Value"]
    _cache[name] = value
    return value


def clear_cache() -> None:
    """Test-only — drop the module cache + client (re-init under moto)."""
    global _client
    _cache.clear()
    _client = None


class SecretMisconfiguredError(RuntimeError):
    """SSM parameter zawiera placeholder lub jest zbyt krótki dla swojego użycia.

    Terraform tworzy SSM params z `value="PLACEHOLDER"`. Po deployu, dopóki
    owner nie wpisze prawdziwych wartości w AWS Console, każdy `get_param`
    zwróci string "PLACEHOLDER" — używanie tego jako secret = fail-open.
    """


def put_param(name: str, value: str, *, secure: bool = True, overwrite: bool = True) -> None:
    """Pisze SSM parameter + uniewazniamy cache lokalnie.

    Sprint 4: OAuth callback persists tokens per-user pod
    `/bodysync/strava/{user_id}/tokens` (SecureString). `overwrite=True`
    bo refresh token rotacja oczekuje update'u tego samego klucza.
    """
    _get_client().put_parameter(
        Name=name,
        Value=value,
        Type="SecureString" if secure else "String",
        Overwrite=overwrite,
    )
    _cache.pop(name, None)


def delete_param(name: str) -> bool:
    """Idempotent delete — returns True jeśli istniał, False jeśli ParameterNotFound.

    Sprint GDPR: account erasure (RODO Art. 17) — kasujemy per-user SSM keys
    (Strava tokens, HAE webhook secret, training-sheet refs). Idempotency
    pozwala retry'om działać bez 500.
    """
    client = _get_client()
    try:
        client.delete_parameter(Name=name)
    except client.exceptions.ParameterNotFound:
        return False
    _cache.pop(name, None)
    return True


def load_secure_secret(name: str, *, min_length: int = 32) -> str:
    """Pobierz SecureString z SSM, fail-fast jeśli PLACEHOLDER lub za krótki.

    `min_length` zależy od użycia:
    - HMAC HS256 (JWT signing): ≥32 chars (256 bits entropy)
    - Webhook Bearer (HAE, Strava): ≥32 chars (collision resistance)
    """
    secret = get_param(name)
    if secret == "PLACEHOLDER" or len(secret) < min_length:
        raise SecretMisconfiguredError(
            f"SSM secret in {name} not configured (must be ≥{min_length} chars, not 'PLACEHOLDER')"
        )
    return secret
