"""Test fixtures dla activity_suggestion (Sprint 10 A0.5).

Mirror pattern z advisor_chat/conftest.py — patchujemy
`service._anthropic_client` na MagicMock, bypass SSM init.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import boto3
import pytest


def _make_json_message(
    *,
    json_text: str = '{"level": "moderate", "reasoning": "4 treningi w 7d, avg 8200 kroków, 580 kcal aktywnych — typowe moderate."}',
    input_tokens: int = 80,
    output_tokens: int = 40,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
) -> Any:
    """Build fake Anthropic Message z text block zawierającym JSON output.

    Mirror SDK shape: `message.content[0]` ma `.type="text"` + `.text=<json>`.
    """
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = json_text

    message = MagicMock()
    message.content = [text_block]
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.cache_read_input_tokens = cache_read_input_tokens
    usage.cache_creation_input_tokens = cache_creation_input_tokens
    message.usage = usage
    return message


@pytest.fixture
def anthropic_json_factory() -> Any:
    """Factory dla fake Message z JSON text block.

    Test może override:
        msg = anthropic_json_factory(json_text='{"level": "heavy", ...}')
        client.messages.create.return_value = msg
    """
    return _make_json_message


@pytest.fixture
def ssm_with_anthropic_key(ssm_params: None) -> Iterator[None]:
    """Pre-seed Anthropic API key (>=50 chars dla load_secure_secret guard)."""
    client = boto3.client("ssm", region_name="eu-west-1")
    client.put_parameter(
        Name="/bodysync/anthropic/api_key",
        Value="sk-ant-api03-test-fake-key-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        Type="SecureString",
        Overwrite=True,
    )
    from shared import ssm as _ssm

    _ssm.clear_cache()
    yield


@pytest.fixture
def patched_anthropic_client(anthropic_json_factory: Any) -> Iterator[MagicMock]:
    """Inject fake Anthropic client jako module singleton — bypass SSM init."""
    from handlers.activity_suggestion import service

    fake_client = MagicMock()
    fake_client.messages.create.return_value = anthropic_json_factory()
    service._anthropic_client = fake_client
    yield fake_client
    service._reset_client_for_tests()
