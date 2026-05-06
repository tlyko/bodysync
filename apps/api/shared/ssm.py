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
