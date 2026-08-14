"""Testy zgodności ze spec MCP — walidacja modelami oficjalnego SDK.

To jest mitygacja głównego minusa decyzji z ADR-010 (surowy JSON-RPC zamiast
FastMCP): pakiet `mcp` siedzi w `requirements-dev.txt`, więc weryfikuje
kształt naszych odpowiedzi, ale NIE ląduje w bundlu Lambdy i nie kosztuje
ani milisekundy cold startu.

Gdy spec się ruszy: bump `mcp` w devach i te testy pokażą, co się rozjechało.

Modele SDK są pydanticowe i mapują camelCase z wire na snake_case w Pythonie,
więc `model_validate` na naszym surowym dict-cie sprawdza jednocześnie nazwy
pól, typy i wymagalność.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

# Import bez `importorskip` celowo: `mcp` jest zadeklarowany w
# [project.optional-dependencies].dev, więc jego brak ma failować głośno.
# Ciche pominięcie tych testów oznaczałoby, że mitygacja z ADR-010 nie działa,
# a nikt by tego nie zauważył.

USER = "tomek"


def _dispatch(message: dict[str, Any]) -> dict[str, Any]:
    from handlers.mcp.protocol import dispatch

    reply = dispatch(message, user_id=USER)
    assert reply is not None, "ta metoda musi zwrócić odpowiedź"
    return reply


def test_initialize_result_matches_sdk_model() -> None:
    """Odpowiedź na `initialize` musi się sparsować jako InitializeResult."""
    from mcp.types import InitializeResult

    reply = _dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2026-07-28",
                "capabilities": {},
                "clientInfo": {"name": "claude", "version": "1.0"},
            },
        }
    )

    parsed = InitializeResult.model_validate(reply["result"])
    assert parsed.server_info.name == "bodysync"
    assert parsed.capabilities.tools is not None, "deklarujemy capability `tools`"
    assert parsed.instructions


def test_advertised_protocol_version_is_known_to_sdk() -> None:
    """Nasza domyślna wersja protokołu nie może być wymyślona — musi być tą,
    którą zna oficjalny SDK."""
    from mcp.types import LATEST_PROTOCOL_VERSION

    from handlers.mcp.protocol import PROTOCOL_VERSION, SUPPORTED_PROTOCOL_VERSIONS

    assert PROTOCOL_VERSION == LATEST_PROTOCOL_VERSION
    assert LATEST_PROTOCOL_VERSION in SUPPORTED_PROTOCOL_VERSIONS


def test_tools_list_result_matches_sdk_model() -> None:
    """Każde narzędzie musi się sparsować jako mcp.types.Tool — to łapie
    literówki w `inputSchema`, brakujące `name` itd."""
    from mcp.types import ListToolsResult

    reply = _dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

    parsed = ListToolsResult.model_validate(reply["result"])
    names = {tool.name for tool in parsed.tools}
    assert names == {
        "get_body_composition",
        "get_daily_health_metrics",
        "get_health_trends",
        "get_workouts",
    }
    for tool in parsed.tools:
        assert tool.description, f"{tool.name} bez opisu — model nie będzie wiedział kiedy go użyć"
        assert tool.input_schema["type"] == "object"


@pytest.mark.usefixtures("dynamodb_table")
def test_call_tool_result_matches_sdk_model() -> None:
    from mcp.types import CallToolResult

    reply = _dispatch(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_workouts", "arguments": {}},
        }
    )

    parsed = CallToolResult.model_validate(reply["result"])
    assert parsed.is_error is False
    assert parsed.content and parsed.content[0].type == "text"


@pytest.mark.usefixtures("dynamodb_table")
def test_tool_input_error_is_a_result_not_a_protocol_error() -> None:
    """Spec: błąd wykonania narzędzia wraca jako CallToolResult z isError,
    a nie jako błąd JSON-RPC — żeby model zobaczył komunikat i poprawił wywołanie."""
    from mcp.types import CallToolResult

    reply = _dispatch(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "get_health_trends", "arguments": {"metric_name": "body_battery"}},
        }
    )

    assert "error" not in reply, "to nie może być błąd protokołu"
    parsed = CallToolResult.model_validate(reply["result"])
    assert parsed.is_error is True
    assert "body_battery" in parsed.content[0].text


def test_mcp_sdk_never_enters_a_lambda_bundle() -> None:
    """Strażnik decyzji z ADR-010.

    `scripts/build.py` instaluje do zipa dokładnie to, co jest w
    handlers/*/requirements.txt. Gdyby ktoś dopisał tam `mcp`, bundle urósłby
    z 15 MB do 22 MB i cold start z ~700 ms do ~1.4 s — czyli cała przewaga,
    dla której piszemy protokół ręcznie, wyparowałaby po cichu.
    """
    handlers_dir = Path(__file__).resolve().parents[3] / "handlers"
    offenders = [
        req.relative_to(handlers_dir.parent).as_posix()
        for req in handlers_dir.glob("*/requirements.txt")
        for line in req.read_text().splitlines()
        if line.strip().lower().split("=")[0].split(">")[0].strip()
        in ("mcp", "mangum", "starlette", "uvicorn")
    ]

    assert not offenders, (
        f"SDK MCP / zależności ASGI trafiły do bundla Lambdy: {offenders}. "
        "To zależność wyłącznie testowa — patrz ADR-010."
    )


def test_mcp_handler_bundle_stays_minimal() -> None:
    """Handler MCP ma jechać na samym boto3 — bez pydantica."""
    handlers_dir = Path(__file__).resolve().parents[3] / "handlers"
    deps = {
        line.strip().lower().split("=")[0].split(">")[0].strip()
        for line in (handlers_dir / "mcp" / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }

    assert "pydantic" not in deps, "pydantic to zmierzone ~490 ms cold startu (ADR-010)"
    assert deps <= {"boto3", "pyjwt"}, f"nieoczekiwane zależności w bundlu MCP: {deps}"


def test_responses_parse_as_jsonrpc_envelopes() -> None:
    """Koperta JSON-RPC musi się walidować modelami SDK — sukces jako
    JSONRPCResponse, błąd jako JSONRPCError."""
    from mcp.types import JSONRPCError, JSONRPCResponse

    ok = _dispatch({"jsonrpc": "2.0", "id": 5, "method": "ping"})
    JSONRPCResponse.model_validate(ok)

    err = _dispatch({"jsonrpc": "2.0", "id": 6, "method": "resources/list"})
    parsed = JSONRPCError.model_validate(err)
    assert parsed.error.code == -32601
