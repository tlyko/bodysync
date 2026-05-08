"""Smoke tests dla POST /api/auth/logout."""

from __future__ import annotations

import json
from types import SimpleNamespace

from handlers.auth_logout.handler import handler


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(aws_request_id="test-req-1")


def test_logout_returns_200_and_clears_cookie() -> None:
    res = handler({"body": ""}, _ctx())
    assert res["statusCode"] == 200
    assert json.loads(res["body"]) == {"ok": True}
    cookies = res["cookies"]
    assert len(cookies) == 1
    cookie = cookies[0]
    assert cookie.startswith("bodysync_session=;")
    assert "Max-Age=0" in cookie
    assert "HttpOnly" in cookie
    assert "Path=/" in cookie


def test_logout_prod_cookie_includes_domain_and_secure() -> None:
    # Default env (no ENV var) → prod path
    res = handler({}, _ctx())
    cookie = res["cookies"][0]
    assert "Domain=.bodysync.pl" in cookie
    assert "Secure" in cookie


def test_logout_local_env_omits_domain_and_secure(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "local")
    res = handler({}, _ctx())
    cookie = res["cookies"][0]
    assert "Domain=" not in cookie
    assert "Secure" not in cookie


def test_logout_idempotent_without_jwt_or_body() -> None:
    # Nie wymaga walidacji JWT — czyści cookie nawet gdy klient nigdy nie miał sesji.
    res = handler({}, _ctx())
    assert res["statusCode"] == 200
