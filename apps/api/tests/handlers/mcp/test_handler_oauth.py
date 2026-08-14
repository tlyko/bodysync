"""Testy warstwy HTTP serwera MCP — routing, ekran zgody i pełny flow OAuth.

Odtwarzają dokładnie tę sekwencję, którą wykona Claude po wklejeniu URL-a
konektora: 401 → discovery → rejestracja → zgoda → token → wywołanie narzędzia.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

CLAUDE_REDIRECT = "https://claude.ai/api/mcp/auth_callback"
VERIFIER = "z" * 64


class _Ctx:
    aws_request_id = "test-request-id"


def _challenge() -> str:
    digest = hashlib.sha256(VERIFIER.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _event(route: str, **kw: Any) -> dict[str, Any]:
    return {
        "routeKey": route,
        "headers": kw.get("headers", {}),
        "cookies": kw.get("cookies", []),
        "queryStringParameters": kw.get("query"),
        "rawQueryString": kw.get("raw_query", ""),
        "body": kw.get("body", ""),
    }


def _session_cookie(user_id: str = "tomek") -> list[str]:
    from shared.auth import mint_jwt

    return [f"bodysync_session={mint_jwt(user_id)}"]


def _seed_profile(user_id: str = "tomek", email: str = "tlyko94@gmail.com") -> None:
    from shared.dynamo import put_item

    put_item(f"USER#{user_id}", "PROFILE", {"email": email, "name": "Tomek"})


# ------------------------------------------------------------- discovery


def test_discovery_documents_are_public(mcp_env: Any) -> None:
    """Dokumenty discovery muszą być dostępne bez tokenu — inaczej klient
    nigdy nie dowie się, gdzie się autoryzować."""
    for route in (
        "GET /.well-known/oauth-protected-resource",
        "GET /.well-known/oauth-authorization-server",
    ):
        resp = mcp_env.handler(_event(route), _Ctx())

        assert resp["statusCode"] == 200
        assert resp["headers"]["Cache-Control"] == "no-store"
        assert json.loads(resp["body"])


def test_unauthenticated_rpc_points_at_resource_metadata(mcp_env: Any) -> None:
    resp = mcp_env.handler(
        _event("POST /mcp", body=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})),
        _Ctx(),
    )

    assert resp["statusCode"] == 401
    assert (
        resp["headers"]["WWW-Authenticate"]
        == 'Bearer resource_metadata="https://api.bodysync.pl/.well-known/oauth-protected-resource"'
    )


# ------------------------------------------------------------- authorize


def _register(mcp_env: Any) -> str:
    resp = mcp_env.handler(
        _event(
            "POST /mcp/register",
            body=json.dumps({"redirect_uris": [CLAUDE_REDIRECT], "client_name": "Claude"}),
        ),
        _Ctx(),
    )
    assert resp["statusCode"] == 201
    return json.loads(resp["body"])["client_id"]


def _authorize_query(client_id: str) -> dict[str, str]:
    return {
        "client_id": client_id,
        "redirect_uri": CLAUDE_REDIRECT,
        "response_type": "code",
        "code_challenge": _challenge(),
        "code_challenge_method": "S256",
        "state": "st-123",
    }


def test_authorize_without_session_redirects_to_login(mcp_env: Any) -> None:
    """Brak cookie → login na froncie, z zapamiętanym powrotem."""
    client_id = _register(mcp_env)
    query = _authorize_query(client_id)

    resp = mcp_env.handler(
        _event("GET /mcp/authorize", query=query, raw_query=urlencode(query)), _Ctx()
    )

    assert resp["statusCode"] == 302
    location = resp["headers"]["Location"]
    assert location.startswith("https://bodysync.pl/?")
    assert "mcp_return_to" in location


def test_authorize_with_session_shows_consent_with_real_email(mcp_env: Any) -> None:
    """Ekran zgody musi pokazać, na które konto udzielasz dostępu."""
    _seed_profile()
    client_id = _register(mcp_env)

    resp = mcp_env.handler(
        _event("GET /mcp/authorize", query=_authorize_query(client_id), cookies=_session_cookie()),
        _Ctx(),
    )

    assert resp["statusCode"] == 200
    assert resp["headers"]["Content-Type"].startswith("text/html")
    assert "tlyko94@gmail.com" in resp["body"]
    assert "request_token" in resp["body"]


def test_consent_post_without_session_is_denied(mcp_env: Any) -> None:
    """Nawet z ważnym request_token — bez sesji nie ma komu udzielić dostępu."""
    from handlers.mcp import oauth

    client_id = _register(mcp_env)
    request = oauth.validate_authorize_request(_authorize_query(client_id))
    token = oauth.mint_request_token(request)

    resp = mcp_env.handler(
        _event("POST /mcp/authorize", body=urlencode({"request_token": token})), _Ctx()
    )

    assert resp["statusCode"] == 401
    assert json.loads(resp["body"])["error"] == "access_denied"


# ------------------------------------------------------------ pełny flow


def test_full_oauth_flow_ends_with_working_tool_call(mcp_env: Any) -> None:
    """Sekwencja, którą wykona Claude po wklejeniu URL-a konektora."""
    from decimal import Decimal

    from shared.biometry import today_iso
    from shared.dynamo import put_item

    _seed_profile()
    put_item("USER#tomek", f"BIOMETRY#{today_iso()}#weight", {"kg": Decimal("73.7")})

    # 1. Rejestracja klienta (DCR) — Claude robi to sam.
    client_id = _register(mcp_env)

    # 2. Zgoda właściciela.
    consent = mcp_env.handler(
        _event("GET /mcp/authorize", query=_authorize_query(client_id), cookies=_session_cookie()),
        _Ctx(),
    )
    request_token = consent["body"].split('name="request_token" value="')[1].split('"')[0]

    granted = mcp_env.handler(
        _event(
            "POST /mcp/authorize",
            body=urlencode({"request_token": request_token}),
            cookies=_session_cookie(),
        ),
        _Ctx(),
    )
    assert granted["statusCode"] == 302
    redirect = urlparse(granted["headers"]["Location"])
    assert f"{redirect.scheme}://{redirect.netloc}{redirect.path}" == CLAUDE_REDIRECT
    params = parse_qs(redirect.query)
    assert params["state"] == ["st-123"], "state musi wrócić nietknięty"
    code = params["code"][0]

    # 3. Wymiana kodu na token.
    token_resp = mcp_env.handler(
        _event(
            "POST /mcp/token",
            body=urlencode(
                {
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": client_id,
                    "redirect_uri": CLAUDE_REDIRECT,
                    "code_verifier": VERIFIER,
                }
            ),
        ),
        _Ctx(),
    )
    assert token_resp["statusCode"] == 200
    access_token = json.loads(token_resp["body"])["access_token"]

    # 4. Wywołanie narzędzia z tokenem.
    rpc = mcp_env.handler(
        _event(
            "POST /mcp",
            headers={"authorization": f"Bearer {access_token}"},
            body=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "get_body_composition", "arguments": {}},
                }
            ),
        ),
        _Ctx(),
    )

    assert rpc["statusCode"] == 200
    payload = json.loads(json.loads(rpc["body"])["result"]["content"][0]["text"])
    assert payload["measurements"][0]["weight"] == 73.7


def test_token_of_one_user_never_returns_another_users_data(mcp_env: Any) -> None:
    """PK isolation na poziomie całego flow, nie tylko warstwy danych."""
    from decimal import Decimal

    from handlers.mcp import oauth
    from shared.biometry import today_iso
    from shared.dynamo import put_item

    put_item("USER#tomek", f"BIOMETRY#{today_iso()}#weight", {"kg": Decimal("84.0")})
    put_item("USER#weronika", f"BIOMETRY#{today_iso()}#weight", {"kg": Decimal("61.0")})

    client_id = _register(mcp_env)
    request = oauth.validate_authorize_request(_authorize_query(client_id))
    code = oauth.issue_authorization_code(request, user_id="weronika")
    tokens = oauth.handle_token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": CLAUDE_REDIRECT,
            "code_verifier": VERIFIER,
        }
    )

    rpc = mcp_env.handler(
        _event(
            "POST /mcp",
            headers={"authorization": f"Bearer {tokens['access_token']}"},
            body=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "get_body_composition", "arguments": {}},
                }
            ),
        ),
        _Ctx(),
    )

    payload = json.loads(json.loads(rpc["body"])["result"]["content"][0]["text"])
    weights = [m["weight"] for m in payload["measurements"]]
    assert weights == [61.0]
    assert 84.0 not in weights


def test_unknown_route_is_404(mcp_env: Any) -> None:
    assert mcp_env.handler(_event("GET /mcp/nieistnieje"), _Ctx())["statusCode"] == 404


def test_token_endpoint_errors_use_rfc6749_codes(mcp_env: Any) -> None:
    """Claude oczekuje `invalid_grant`, nie własnego kodu — inaczej nie wie,
    że ma odświeżyć autoryzację."""
    resp = mcp_env.handler(
        _event(
            "POST /mcp/token",
            body=urlencode({"grant_type": "authorization_code", "code": "zmyslony"}),
        ),
        _Ctx(),
    )

    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error"] == "invalid_grant"
