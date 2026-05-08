"""Regression tests for `shared.logging.JsonFormatter`.

H1 (Sprint 6.1 security review): formatter allowlist musi przepuszczać pola
tokenowe Anthropic, inaczej cost-guard CloudWatch metric filter widzi 0 i alarm
1.5M output tokens/dzień nigdy się nie odpala. Patrz `infrastructure/terraform/
cloudwatch.tf` — pattern `{ $.msg = "anthropic_call" }` + `value = $.input_tokens`.
"""

from __future__ import annotations

import json
import logging

from shared.logging import JsonFormatter


def _format(record: logging.LogRecord) -> dict[str, object]:
    payload: dict[str, object] = json.loads(JsonFormatter().format(record))
    return payload


def _make_record(msg: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_anthropic_token_fields_present_in_output() -> None:
    """Cost-guard CloudWatch metric filter regression — wszystkie 4 pola tokenowe
    + `model` muszą trafić do JSON line, inaczej alarm jest dekoracyjny."""
    record = _make_record(
        "anthropic_call",
        input_tokens=1234,
        output_tokens=567,
        cache_read_input_tokens=100,
        cache_creation_input_tokens=50,
        model="claude-haiku-4-5-20251001",
    )
    payload = _format(record)
    assert payload["msg"] == "anthropic_call"
    assert payload["input_tokens"] == 1234
    assert payload["output_tokens"] == 567
    assert payload["cache_read_input_tokens"] == 100
    assert payload["cache_creation_input_tokens"] == 50
    assert payload["model"] == "claude-haiku-4-5-20251001"


def test_unknown_extra_fields_are_dropped() -> None:
    """Allowlist policy — payload content NIE może wyciec do logów."""
    record = _make_record(
        "chat_turn_complete",
        user_id="user_a",
        request_id="req-1",
        message="sekretna wiadomość użytkownika",
        secret="sk-ant-...",
    )
    payload = _format(record)
    assert payload["user_id"] == "user_a"
    assert payload["request_id"] == "req-1"
    assert "message" not in payload
    assert "secret" not in payload
