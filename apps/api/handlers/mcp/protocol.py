"""JSON-RPC 2.0 + dispatch metod MCP.

Pełna powierzchnia stateless serwera read-only to pięć metod: `initialize`,
`notifications/initialized`, `tools/list`, `tools/call`, `ping`. Metody
capabilities, których nie deklarujemy (`resources/*`, `prompts/*`), zwracają
`-32601` — zgodnie ze spec.

Batche JSON-RPC zostały usunięte ze spec MCP w rewizji 2025-06-18, więc
tablica na wejściu to `-32600`, a nie pętla po elementach.

Zgodność z modelami oficjalnego SDK weryfikują testy w
`tests/handlers/mcp/test_conformance.py` — SDK jest zależnością dev, nigdy
nie ląduje w bundlu Lambdy (ADR-010).
"""

from __future__ import annotations

import json
from typing import Any

from handlers.mcp import tools
from handlers.mcp.service import ToolInputError
from shared.logging import get_logger

logger = get_logger("mcp")

JSONRPC_VERSION = "2.0"

# Wersja protokołu, którą ogłaszamy gdy klient poprosi o nieznaną nam.
# `LATEST_PROTOCOL_VERSION` z oficjalnego SDK na dzień 2026-08-14.
PROTOCOL_VERSION = "2026-07-28"
SUPPORTED_PROTOCOL_VERSIONS = (
    "2026-07-28",
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
)

SERVER_INFO = {
    "name": "bodysync",
    "title": "bodysync — dane zdrowotne",
    "version": "1.0.0",
}

INSTRUCTIONS = (
    "Dane zdrowotne i treningowe z bodysync: skład ciała, metryki dzienne z Apple Health "
    "(kalorie, makro, kroki, sen, tętno) oraz historia treningów siłowych. Wszystko "
    "wyłącznie do odczytu.\n\n"
    "Czego tu NIE ma: aktywności cardio ze Stravy (osobny konektor), HRV i Body Battery "
    "(Garmin nie wysyła ich do Apple Health, więc te dane nie istnieją w bazie — nie "
    "próbuj ich szukać ani nie zakładaj, że brak wyniku oznacza zero).\n\n"
    "Dane bieżącego dnia bywają niekompletne do wieczora, bo Health Auto Export wysyła "
    "paczki cyklicznie."
)

# Kody błędów JSON-RPC 2.0.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": JSONRPC_VERSION,
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _tool_result(payload: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    """CallToolResult. Treść jako JSON w bloku tekstowym — czytelne dla modelu
    i kompatybilne z każdym klientem."""
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
        "isError": is_error,
    }


def _negotiate_version(requested: Any) -> str:
    """Zwraca wersję protokołu, którą serwer będzie mówił.

    Spec: jeśli wspieramy wersję klienta — odsyłamy ją. Jeśli nie —
    odsyłamy swoją najnowszą i to klient decyduje, czy kontynuować.
    """
    if isinstance(requested, str) and requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return PROTOCOL_VERSION


def dispatch(message: Any, *, user_id: str) -> dict[str, Any] | None:
    """Obsługuje jedną wiadomość JSON-RPC.

    Zwraca dict do odesłania albo `None` dla notyfikacji (brak `id` → brak
    odpowiedzi, zgodnie z JSON-RPC 2.0).
    """
    if isinstance(message, list):
        # Batche usunięte ze spec MCP w 2025-06-18.
        return _error(None, INVALID_REQUEST, "batche JSON-RPC nie są wspierane")
    if not isinstance(message, dict):
        return _error(None, INVALID_REQUEST, "oczekiwano obiektu JSON-RPC")

    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}
    if not isinstance(method, str):
        return _error(request_id, INVALID_REQUEST, "brak pola `method`")
    if not isinstance(params, dict):
        return _error(request_id, INVALID_PARAMS, "`params` musi być obiektem")

    is_notification = "id" not in message

    if method == "notifications/initialized":
        return None
    if method.startswith("notifications/"):
        return None

    if is_notification:
        # Metoda wymagająca odpowiedzi, ale przysłana jako notyfikacja —
        # nie ma komu odpowiedzieć.
        return None

    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": _negotiate_version(params.get("protocolVersion")),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": INSTRUCTIONS,
            },
        )

    if method == "ping":
        return _result(request_id, {})

    if method == "tools/list":
        return _result(request_id, {"tools": tools.TOOLS})

    if method == "tools/call":
        return _handle_tools_call(request_id, params, user_id=user_id)

    return _error(request_id, METHOD_NOT_FOUND, f"nieznana metoda: {method}")


def _handle_tools_call(request_id: Any, params: dict[str, Any], *, user_id: str) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(name, str):
        return _error(request_id, INVALID_PARAMS, "`name` musi być stringiem")
    if not isinstance(arguments, dict):
        return _error(request_id, INVALID_PARAMS, "`arguments` musi być obiektem")
    if name not in tools._DISPATCH:
        return _error(request_id, INVALID_PARAMS, f"nieznane narzędzie: {name}")

    try:
        payload = tools.call(name, arguments, user_id=user_id)
    except ToolInputError as exc:
        # Błąd inputu wraca jako wynik narzędzia z isError, nie jako błąd
        # protokołu — dzięki temu model widzi komunikat i może poprawić wywołanie.
        logger.info("mcp_tool_input_error", extra={"tool": name, "user_id": user_id})
        return _result(request_id, _tool_result({"error": str(exc)}, is_error=True))
    except Exception:
        # Nie wypuszczamy stack trace'a do modelu — logujemy po stronie serwera.
        logger.exception("mcp_tool_failed", extra={"tool": name, "user_id": user_id})
        return _result(
            request_id,
            _tool_result(
                {
                    "error": f"narzędzie {name} nie zadziałało; spróbuj ponownie lub zawęź zakres dat"
                },
                is_error=True,
            ),
        )

    logger.info("mcp_tool_ok", extra={"tool": name, "user_id": user_id})
    return _result(request_id, _tool_result(payload))
