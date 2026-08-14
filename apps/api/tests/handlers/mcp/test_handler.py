"""Tests dla `handlers.mcp.handler` — transport JSON-RPC na `POST /mcp`.

Flow OAuth (discovery, rejestracja, zgoda, token) siedzi w
`test_handler_oauth.py`; tutaj zostaje sama warstwa transportowa.
"""

from __future__ import annotations

import json
from typing import Any

import pytest


class _Ctx:
    aws_request_id = "test-request-id"


def _rpc_event(body: Any = None, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "routeKey": "POST /mcp",
        "headers": headers or {},
        "cookies": [],
        "body": json.dumps(body) if body is not None else "",
    }


def test_request_without_token_is_401_with_www_authenticate() -> None:
    """Spec: Claude nie honoruje WWW-Authenticate na 200 — musi być 401,
    a nagłówek musi wskazywać protected resource metadata."""
    from handlers.mcp import handler as h

    resp = h.handler(_rpc_event({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}), _Ctx())

    assert resp["statusCode"] == 401
    www = resp["headers"]["WWW-Authenticate"]
    assert www.startswith("Bearer ")
    assert 'resource_metadata="https://api.bodysync.pl/.well-known/oauth-protected-resource"' in www


def test_garbage_bearer_token_is_rejected(mcp_env: Any) -> None:
    """Token, którego nie wystawiliśmy, nie może przejść."""
    from handlers.mcp import handler as h

    resp = h.handler(
        _rpc_event(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"authorization": "Bearer cokolwiek"},
        ),
        _Ctx(),
    )

    assert resp["statusCode"] == 401


def test_no_tool_data_leaks_in_unauthorized_response() -> None:
    """401 nie może zdradzić nawet listy narzędzi."""
    from handlers.mcp import handler as h

    resp = h.handler(
        _rpc_event(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_workouts", "arguments": {}},
            }
        ),
        _Ctx(),
    )

    assert resp["statusCode"] == 401
    assert "get_workouts" not in resp["body"]


def test_oversized_body_rejected_before_auth_and_parsing() -> None:
    """Limit rozmiaru działa zanim dotkniemy tokenu i JSON-a."""
    from handlers.mcp import handler as h

    event = _rpc_event()
    event["body"] = "x" * (h.MAX_BODY_BYTES + 1)

    assert h.handler(event, _Ctx())["statusCode"] == 413


def test_malformed_json_returns_parse_error(monkeypatch: Any) -> None:
    from handlers.mcp import handler as h

    monkeypatch.setattr(h, "resolve_user_id", lambda event: "tomek")

    event = _rpc_event()
    event["body"] = "{nie-json"
    resp = h.handler(event, _Ctx())

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"]["code"] == -32700


def test_notification_returns_202_with_empty_body(monkeypatch: Any) -> None:
    """JSON-RPC: notyfikacja nie dostaje odpowiedzi."""
    from handlers.mcp import handler as h

    monkeypatch.setattr(h, "resolve_user_id", lambda event: "tomek")

    resp = h.handler(_rpc_event({"jsonrpc": "2.0", "method": "notifications/initialized"}), _Ctx())

    assert resp["statusCode"] == 202
    assert resp["body"] == ""


def test_authorized_request_reaches_dispatch(monkeypatch: Any) -> None:
    from handlers.mcp import handler as h

    monkeypatch.setattr(h, "resolve_user_id", lambda event: "tomek")

    resp = h.handler(_rpc_event({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}), _Ctx())

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert {t["name"] for t in body["result"]["tools"]} == {
        "get_body_composition",
        "get_daily_health_metrics",
        "get_health_trends",
        "get_workouts",
    }


@pytest.mark.parametrize("route", ["GET /mcp", "DELETE /mcp", "GET /mcp/token"])
def test_unregistered_routes_are_404(route: str) -> None:
    """Kanał SSE (GET /mcp) świadomie nie istnieje — API Gateway i tak nie
    streamuje odpowiedzi."""
    from handlers.mcp import handler as h

    event = _rpc_event()
    event["routeKey"] = route

    assert h.handler(event, _Ctx())["statusCode"] == 404
