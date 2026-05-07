"""SSM Parameter Store reads with module-level cache.

Cold start cost: ~30-100ms per parameter. Warm Lambda re-uses module globals,
so cache survives across invocations until container freeze.
"""

from __future__ import annotations

import boto3

_client = boto3.client("ssm")
_cache: dict[str, str] = {}


def get_param(name: str, *, decrypt: bool = True) -> str:
    """Fetch SSM parameter, cached for the lifetime of the Lambda container.

    Use `decrypt=True` for SecureString. String/StringList tolerate it too.
    """
    cached = _cache.get(name)
    if cached is not None:
        return cached
    resp = _client.get_parameter(Name=name, WithDecryption=decrypt)
    value: str = resp["Parameter"]["Value"]
    _cache[name] = value
    return value


def clear_cache() -> None:
    """Test-only — drop the module cache between fixtures."""
    _cache.clear()


class SecretMisconfiguredError(RuntimeError):
    """SSM parameter zawiera placeholder lub jest zbyt krótki dla swojego użycia.

    Terraform tworzy SSM params z `value="PLACEHOLDER"`. Po deployu, dopóki
    owner nie wpisze prawdziwych wartości w AWS Console, każdy `get_param`
    zwróci string "PLACEHOLDER" — używanie tego jako secret = fail-open.
    """


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
