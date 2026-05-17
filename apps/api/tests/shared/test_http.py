"""Tests dla shared/http extract_session_cookie + response helpers."""

from __future__ import annotations

import json
from decimal import Decimal

from shared.http import extract_session_cookie, response


def test_extract_session_cookie_from_array() -> None:
    event = {"cookies": ["bodysync_session=abc.def.ghi", "other=foo"]}
    assert extract_session_cookie(event) == "abc.def.ghi"


def test_extract_session_cookie_from_header_fallback() -> None:
    event = {"cookies": [], "headers": {"cookie": "x=1; bodysync_session=tok; y=2"}}
    assert extract_session_cookie(event) == "tok"


def test_extract_session_cookie_case_insensitive_header() -> None:
    event = {"cookies": [], "headers": {"Cookie": "bodysync_session=case"}}
    assert extract_session_cookie(event) == "case"


def test_extract_session_cookie_returns_none_when_missing() -> None:
    assert extract_session_cookie({"cookies": [], "headers": {}}) is None


def test_response_envelope_shape() -> None:
    r = response(200, {"ok": True})
    assert r["statusCode"] == 200
    assert r["headers"]["Content-Type"] == "application/json"
    assert json.loads(r["body"]) == {"ok": True}


def test_response_serializes_decimal_via_default_str() -> None:
    """DDB N attrs come back as Decimal — fallback default=str renders as string."""
    r = response(200, {"value": Decimal("10.5")})
    assert json.loads(r["body"]) == {"value": "10.5"}


def test_response_accepts_list_body() -> None:
    r = response(200, [{"a": 1}, {"b": 2}])
    assert json.loads(r["body"]) == [{"a": 1}, {"b": 2}]
