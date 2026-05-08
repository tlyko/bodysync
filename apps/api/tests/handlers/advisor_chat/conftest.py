"""Test fixtures dla advisor_chat (Sprint 6.1 PR1 + 6.2 PR2).

`anthropic_mock_factory` / `patched_anthropic_client` — patchujemy
`service._anthropic_client` na fake `MagicMock` z `messages.create` zwracającym
`Message`-like obiekt z **single text block** (`content[0].type == "text"`)
+ `usage` shape mirror Anthropic SDK.

NIE używamy `responses` lib — Anthropic SDK używa custom httpx client z retry,
trudniej zamockować na poziomie HTTP. Fake client jako module singleton jest
prostszy i deterministic.

`ssm_with_anthropic_key` rozszerza global `ssm_params` o anthropic api_key
(>=50 chars dla `load_secure_secret` guard).

`dynamodb_table_with_chat_history` — pre-seed 5 turn dla `user_a` (PK isolation
regression: user_b ma 0 turn).

`_disable_rag_by_default` (autouse) — Sprint 6.2 PR2: monkeypatch'uje
`rag.retrieve` żeby rzucał `RAGUnavailableError("test_default")`. Bez tego
każdy handler test dotknąłby S3 (faiss-index.bin missing) + OpenAI (key
PLACEHOLDER) i failowałby cold-start init. Test który chce realne
retrieved recipes nadpisuje przez własny `monkeypatch.setattr("...rag.retrieve", ...)`.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import boto3
import pytest

WARSAW_TZ = ZoneInfo("Europe/Warsaw")


@pytest.fixture(autouse=True)
def _disable_rag_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default — `rag.retrieve` rzuca `RAGUnavailableError` => handler
    kontynuuje bez recipes (graceful degradation path).

    Test który chce realne retrieve override'uje przez własny
    `monkeypatch.setattr("handlers.advisor_chat.rag.retrieve", lambda q, k=5: [...])`.
    """
    from handlers.advisor_chat import rag

    def _fake_retrieve(query: str, k: int = 5) -> list[Any]:
        raise rag.RAGUnavailableError("test_default")

    monkeypatch.setattr(rag, "retrieve", _fake_retrieve)


@pytest.fixture
def ssm_with_anthropic_key(ssm_params: None) -> Iterator[None]:
    """Pre-seed Anthropic API key (>=50 chars)."""
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


def _make_text_message(
    *,
    text: str = "OK, przygotowałem dla Ciebie krótką odpowiedź po polsku.",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
) -> Any:
    """Build fake Anthropic Message z **single text block** (NIE tool_use).

    Mirror SDK shape: `message.content` to lista `ContentBlock` z `.type/.text`.
    `message.usage` z `input_tokens/output_tokens/cache_*`.
    """
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = text

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
def anthropic_mock_factory() -> Any:
    """Factory zwraca fake Message z **text block**.

    Test może override per scenariusz przez przekazanie kwargs:
        msg = anthropic_mock_factory(text="..", input_tokens=200)
        client.messages.create.return_value = msg
    """
    return _make_text_message


@pytest.fixture
def patched_anthropic_client(anthropic_mock_factory: Any) -> Iterator[MagicMock]:
    """Inject fake Anthropic client jako module singleton — bypass SSM init.

    Test może override `mock.messages.create.return_value` lub `.side_effect`
    dla scenariuszy retry / error.
    """
    from handlers.advisor_chat import service

    fake_client = MagicMock()
    fake_client.messages.create.return_value = anthropic_mock_factory()
    service._anthropic_client = fake_client
    yield fake_client
    service._reset_client_for_tests()


def _seed_chat_turn(
    table: Any,
    user_id: str,
    *,
    today_iso: str,
    turn_idx: int,
    role: str,
    content: str,
) -> None:
    """Mirror co `service.append_message` zapisuje do DDB.

    SK format: `CHAT#{today}#{turn_idx:04d}` (zero-padded 4-cyfry).
    """
    sk = f"CHAT#{today_iso}#{turn_idx:04d}"
    item: dict[str, Any] = {
        "PK": f"USER#{user_id}",
        "SK": sk,
        "role": role,
        "content": content,
        "ts": f"{today_iso}T12:00:0{turn_idx % 10}+00:00",
        "ttl": int(time.time()) + 86400,
    }
    table.put_item(Item=item)


@pytest.fixture
def dynamodb_table_with_chat_history(dynamodb_table: Any) -> Any:
    """Pre-seed 5 turn dla `user_a` (turny 0-4 alternating user/assistant);
    user_b ma 0 turn (PK isolation regression).

    Date = today w WARSAW_TZ (matches `handler.py` line `today = datetime.now(WARSAW_TZ).date()`).
    """
    today_iso = datetime.now(WARSAW_TZ).date().isoformat()
    turns = [
        (0, "user", "Co zjeść na obiad?"),
        (1, "assistant", "Polecam łososia z ryżem i brokułem."),
        (2, "user", "A coś bez ryby?"),
        (3, "assistant", "Kurczak z kaszą gryczaną i sałatką."),
        (4, "user", "Ile białka w tym?"),
    ]
    for turn_idx, role, content in turns:
        _seed_chat_turn(
            dynamodb_table,
            "user_a",
            today_iso=today_iso,
            turn_idx=turn_idx,
            role=role,
            content=content,
        )
    return dynamodb_table
