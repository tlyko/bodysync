"""Tests dla `handlers.mcp.handler` — warstwa HTTP i handshake 401.

Auth dochodzi w PR 4; tutaj sprawdzamy, że do tego czasu handler NIE zwraca
danych bez tokenu i że kształt 401 jest już zgodny ze spec (to on uruchamia
discovery OAuth po stronie Claude).
"""

from __future__ import annotations

import json
from typing import Any


class _Ctx:
    aws_request_id = "test-request-id"


def _event(
    body: Any = None, *, method: str = "POST", headers: dict[str, str] | None = None
) -> dict[str, Any]:
    return {
        "requestContext": {"http": {"method": method}},
        "headers": headers or {},
        "body": json.dumps(body) if body is not None else "",
    }


def test_request_without_token_is_401_with_www_authenticate() -> None:
    """Spec: Claude nie honoruje WWW-Authenticate na 200 — musi być 401,
    a nagłówek musi wskazywać protected resource metadata."""
    from handlers.mcp import handler as h

    resp = h.handler(_event({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}), _Ctx())

    assert resp["statusCode"] == 401
    www = resp["headers"]["WWW-Authenticate"]
    assert www.startswith("Bearer ")
    assert 'resource_metadata="https://api.bodysync.pl/.well-known/oauth-protected-resource"' in www


def test_bearer_token_still_rejected_until_pr4() -> None:
    """Token jest parsowany, ale weryfikacja nie istnieje — musi odrzucać,
    a nie przepuszczać."""
    from handlers.mcp import handler as h

    resp = h.handler(
        _event(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"authorization": "Bearer cokolwiek"},
        ),
        _Ctx(),
    )

    assert resp["statusCode"] == 401


def test_no_tool_data_leaks_in_unauthorized_response() -> None:
    """401 nie może zawierać żadnych danych zdrowotnych ani listy narzędzi."""
    from handlers.mcp import handler as h

    resp = h.handler(
        _event(
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


def test_get_is_not_allowed() -> None:
    """Kanał SSE (GET) nie jest wystawiony — API Gateway i tak nie streamuje."""
    from handlers.mcp import handler as h

    resp = h.handler(_event(method="GET"), _Ctx())

    assert resp["statusCode"] == 405


def test_malformed_json_returns_parse_error(monkeypatch: Any) -> None:
    from handlers.mcp import auth
    from handlers.mcp import handler as h

    monkeypatch.setattr(auth, "resolve_user_id", lambda event: "tomek")
    monkeypatch.setattr(h, "resolve_user_id", lambda event: "tomek")

    event = _event()
    event["body"] = "{nie-json"
    resp = h.handler(event, _Ctx())

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"]["code"] == -32700


def test_oversized_body_rejected_before_parsing() -> None:
    from handlers.mcp import handler as h

    event = _event()
    event["body"] = "x" * (h.MAX_BODY_BYTES + 1)
    resp = h.handler(event, _Ctx())

    assert resp["statusCode"] == 413


def test_notification_returns_202_with_empty_body(monkeypatch: Any) -> None:
    """JSON-RPC: notyfikacja nie dostaje odpowiedzi."""
    from handlers.mcp import handler as h

    monkeypatch.setattr(h, "resolve_user_id", lambda event: "tomek")

    resp = h.handler(_event({"jsonrpc": "2.0", "method": "notifications/initialized"}), _Ctx())

    assert resp["statusCode"] == 202
    assert resp["body"] == ""


def test_authorized_request_reaches_dispatch(monkeypatch: Any) -> None:
    """Gdy PR 4 podmieni resolve_user_id, reszta ścieżki ma działać."""
    from handlers.mcp import handler as h

    monkeypatch.setattr(h, "resolve_user_id", lambda event: "tomek")

    resp = h.handler(_event({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}), _Ctx())

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert {t["name"] for t in body["result"]["tools"]} == {
        "get_body_composition",
        "get_daily_health_metrics",
        "get_health_trends",
        "get_workouts",
    }
