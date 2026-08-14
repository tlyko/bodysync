"""Tests dla `handlers.mcp.protocol` — dispatch JSON-RPC i kontrakt metod."""

from __future__ import annotations

from typing import Any

USER = "tomek"


def _dispatch(message: Any) -> Any:
    from handlers.mcp.protocol import dispatch

    return dispatch(message, user_id=USER)


def test_notification_returns_no_response() -> None:
    """`notifications/initialized` nie ma `id` → brak odpowiedzi (JSON-RPC 2.0)."""
    assert _dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_batch_is_rejected() -> None:
    """Batche usunięte ze spec MCP w rewizji 2025-06-18."""
    reply = _dispatch([{"jsonrpc": "2.0", "id": 1, "method": "ping"}])

    assert reply["error"]["code"] == -32600


def test_unknown_method_returns_method_not_found() -> None:
    reply = _dispatch({"jsonrpc": "2.0", "id": 1, "method": "prompts/list"})

    assert reply["error"]["code"] == -32601


def test_missing_method_field_is_invalid_request() -> None:
    reply = _dispatch({"jsonrpc": "2.0", "id": 1})

    assert reply["error"]["code"] == -32600


def test_non_object_params_is_invalid_params() -> None:
    reply = _dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": []})

    assert reply["error"]["code"] == -32602


def test_initialize_echoes_supported_client_version() -> None:
    """Spec: gdy wspieramy wersję klienta, odsyłamy dokładnie ją."""
    reply = _dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        }
    )

    assert reply["result"]["protocolVersion"] == "2025-06-18"


def test_initialize_falls_back_to_own_version_when_client_unknown() -> None:
    """Nieznana wersja klienta → odsyłamy swoją najnowszą, klient decyduje."""
    from handlers.mcp.protocol import PROTOCOL_VERSION

    reply = _dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "1999-01-01"},
        }
    )

    assert reply["result"]["protocolVersion"] == PROTOCOL_VERSION


def test_instructions_warn_about_missing_data_sources() -> None:
    """Instrukcje muszą uprzedzić model, że Stravy/HRV/Body Battery tu nie ma —
    inaczej będzie ich szukał albo uzna brak wyniku za zero."""
    reply = _dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})

    instructions = reply["result"]["instructions"].lower()
    assert "strav" in instructions
    assert "hrv" in instructions
    assert "body battery" in instructions


def test_unknown_tool_name_is_invalid_params() -> None:
    reply = _dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "drop_table", "arguments": {}},
        }
    )

    assert reply["error"]["code"] == -32602


def test_tool_crash_does_not_leak_stack_trace(monkeypatch: Any) -> None:
    """Nieoczekiwany wyjątek w narzędziu → czytelny komunikat, nie traceback."""
    from handlers.mcp import protocol, tools

    def _boom(user_id: str, args: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("DDB ProvisionedThroughputExceededException: sekret w treści")

    monkeypatch.setitem(tools._DISPATCH, "get_workouts", _boom)

    reply = protocol.dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "get_workouts", "arguments": {}},
        },
        user_id=USER,
    )

    text = reply["result"]["content"][0]["text"]
    assert reply["result"]["isError"] is True
    assert "sekret" not in text
    assert "Traceback" not in text
