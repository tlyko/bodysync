"""AWS Lambda entry point serwera MCP — Streamable HTTP (POST, bez SSE).

`POST /mcp` przyjmuje pojedynczą wiadomość JSON-RPC 2.0 i odpowiada
`application/json`. SSE nie jest używane świadomie: API Gateway HTTP nie
wspiera response streamingu, a przy czterech narzędziach read-only nie ma
czego streamować (ADR-010).

Auth: OAuth 2.0 Bearer. Request bez ważnego tokenu dostaje `401` z nagłówkiem
`WWW-Authenticate` wskazującym protected resource metadata — to jest handshake,
od którego Claude zaczyna flow autoryzacji.
"""

from __future__ import annotations

import json
from typing import Any

from handlers.mcp import protocol
from handlers.mcp.auth import AuthError, resolve_user_id
from shared.logging import get_logger

logger = get_logger("mcp")

# Adres protected resource metadata. PR 4 wystawi ten dokument; nagłówek
# wskazuje na niego już teraz, bo to on uruchamia discovery po stronie klienta.
RESOURCE_METADATA_URL = "https://api.bodysync.pl/.well-known/oauth-protected-resource"

MAX_BODY_BYTES = 256 * 1024


def _response(
    status: int, body: dict[str, Any] | None, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", **(headers or {})},
    }
    out["body"] = json.dumps(body, ensure_ascii=False) if body is not None else ""
    return out


def _unauthorized(detail: str) -> dict[str, Any]:
    """401 z WWW-Authenticate — start flow OAuth po stronie klienta.

    Spec wymaga statusu 401; Claude nie honoruje `WWW-Authenticate` na 200.
    """
    return _response(
        401,
        {"error": "unauthorized", "detail": detail},
        {"WWW-Authenticate": f'Bearer resource_metadata="{RESOURCE_METADATA_URL}"'},
    )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "local")

    method = (event.get("requestContext") or {}).get("http", {}).get("method", "POST")
    if method != "POST":
        # Streamable HTTP dopuszcza GET dla kanału SSE — my go nie wystawiamy.
        return _response(
            405, {"error": "method not allowed", "detail": "serwer przyjmuje wyłącznie POST"}
        )

    raw = event.get("body") or ""
    if len(raw) > MAX_BODY_BYTES:
        return _response(413, {"error": "payload too large"})

    try:
        user_id = resolve_user_id(event)
    except AuthError as exc:
        logger.info("mcp_unauthorized", extra={"request_id": request_id, "reason": str(exc)})
        return _unauthorized(str(exc))

    try:
        message = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        logger.info("mcp_parse_error", extra={"request_id": request_id})
        return _response(
            400,
            {
                "jsonrpc": protocol.JSONRPC_VERSION,
                "id": None,
                "error": {
                    "code": protocol.PARSE_ERROR,
                    "message": "body nie jest poprawnym JSON-em",
                },
            },
        )

    reply = protocol.dispatch(message, user_id=user_id)

    if reply is None:
        # Notyfikacja — JSON-RPC nie przewiduje odpowiedzi. 202 bez ciała.
        return _response(202, None)

    return _response(200, reply)
