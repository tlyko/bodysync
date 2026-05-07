"""Test fixtures for advisor_dinner.

`anthropic_client` mock — nie używamy `responses` lib (Anthropic SDK używa
custom httpx client z retry, trudniej zamockować na poziomie HTTP). Zamiast
tego patchujemy `service._anthropic_client` na fake object z `messages.create`
zwracającym `Message`-like Mock z `content[].tool_use` i `usage`.

`ssm_with_anthropic_key` rozszerza global `ssm_params` o anthropic api_key
(>50 chars dla load_secure_secret guard).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import boto3
import pytest


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


def _make_tool_use_message(
    *,
    summary: str = "Dziś deficyt 400 kcal i mocny trening — kolacja z naciskiem na białko.",
    target_dinner_kcal: int = 650,
    target_dinner_protein_g: int = 45,
    target_dinner_fat_g: int = 22,
    target_dinner_carbs_g: int = 65,
    suggestions: list[dict[str, Any]] | None = None,
    input_tokens: int = 850,
    output_tokens: int = 420,
) -> Any:
    """Zbuduj fake Anthropic Message z tool_use content block.

    Mirror real SDK shape: `message.content` to lista `ContentBlock` z
    `.type/.name/.input` (tool_use) lub `.type/.text` (text). `message.usage`
    z `input_tokens/output_tokens/cache_*`.
    """
    if suggestions is None:
        suggestions = [
            {
                "name": "Pieczony łosoś z brokułem i ryżem",
                "kcal": 620,
                "protein_g": 42,
                "fat_g": 24,
                "carbs_g": 58,
                "description": "150 g łososia, 200 g brokułu, 100 g ryżu basmati. Łosoś z piekarnika 200°C 12 min, ryż gotowany w bulionie.",
                "why": "Wysoka zawartość białka i omega-3 wspiera regenerację po treningu siłowym.",
            },
            {
                "name": "Sałatka z kurczakiem i awokado",
                "kcal": 580,
                "protein_g": 48,
                "fat_g": 26,
                "carbs_g": 30,
                "description": "150 g kurczaka grillowanego, mix sałat, 1/2 awokado, ogórek, oliwa z cytryną.",
                "why": "Lekka kolacja po dużym kcal_in lunch — sytość z białka i tłuszczu.",
            },
            {
                "name": "Omlet z 4 jajek z warzywami",
                "kcal": 540,
                "protein_g": 40,
                "fat_g": 30,
                "carbs_g": 18,
                "description": "4 jajka, papryka, szpinak, cebula, kromka pełnoziarnistego pieczywa.",
                "why": "Szybka opcja gdy mało czasu — białko + tłuszcz dla sytości na noc.",
            },
        ]

    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.name = "dinner_advisor_response"
    tool_use_block.input = {
        "summary": summary,
        "target_dinner_kcal": target_dinner_kcal,
        "target_dinner_protein_g": target_dinner_protein_g,
        "target_dinner_fat_g": target_dinner_fat_g,
        "target_dinner_carbs_g": target_dinner_carbs_g,
        "suggestions": suggestions,
    }

    message = MagicMock()
    message.content = [tool_use_block]
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.cache_read_input_tokens = 0
    usage.cache_creation_input_tokens = input_tokens  # pierwszy call → cache write
    message.usage = usage
    return message


@pytest.fixture
def anthropic_mock_factory() -> Any:
    """Factory zwraca fake Message z tool_use block. Test układa scenariusz
    przekazując kwargs do helpera (overide kcal targets, suggestions, etc.).

    Przykład:
        client = MagicMock()
        client.messages.create.return_value = anthropic_mock_factory()
        from handlers.advisor_dinner import service
        service._anthropic_client = client
    """
    return _make_tool_use_message


@pytest.fixture
def patched_anthropic_client(anthropic_mock_factory: Any) -> Iterator[MagicMock]:
    """Inject fake Anthropic client jako module singleton — bypass SSM
    + SDK init. Test może override `mock.messages.create.return_value`
    lub `.side_effect` dla scenariuszy retry / error.
    """
    from handlers.advisor_dinner import service

    fake_client = MagicMock()
    fake_client.messages.create.return_value = anthropic_mock_factory()
    service._anthropic_client = fake_client
    yield fake_client
    service._reset_client_for_tests()
