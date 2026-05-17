"""Shared Anthropic SDK singleton — reused przez handlers/{advisor_chat, workouts_extract}.

Każdy handler i tak mocuje response przez `responses` lib w testach, więc
singleton w module-level globals jest bezpieczny (kolizja state'u tylko gdy
test kontaminuje globals — fixture `_reset_client_for_tests` chroni).

Cold start cost: Anthropic SDK ~3s import — `from anthropic import Anthropic`
jest LAZY w `get_anthropic_client` żeby testy mockujące przez httpx_mock /
responses nie płaciły. Po pierwszym wywołaniu trzymane w `_client` global.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from shared.ssm import SecretMisconfiguredError, load_secure_secret

if TYPE_CHECKING:
    from anthropic import Anthropic

ANTHROPIC_API_KEY_PARAM = "/bodysync/anthropic/api_key"
ANTHROPIC_API_KEY_MIN_LENGTH = 50

_client: Anthropic | None = None


class AnthropicUnavailableError(RuntimeError):
    """Anthropic API key niedostępny (SSM PLACEHOLDER) lub init failed."""


def get_anthropic_client() -> Anthropic:
    """Lazy singleton — Anthropic SDK init + SSM key fetch raz per cold start."""
    global _client
    if _client is not None:
        return _client
    try:
        api_key = load_secure_secret(
            ANTHROPIC_API_KEY_PARAM, min_length=ANTHROPIC_API_KEY_MIN_LENGTH
        )
    except SecretMisconfiguredError as exc:
        raise AnthropicUnavailableError("anthropic_api_key_missing") from exc
    from anthropic import Anthropic

    _client = Anthropic(api_key=api_key, max_retries=2)
    return _client


def reset_client_for_tests() -> None:
    """Test-only — drop singleton between tests."""
    global _client
    _client = None
