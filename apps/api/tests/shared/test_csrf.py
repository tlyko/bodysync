"""Tests for shared/csrf double-submit cookie verification."""

from __future__ import annotations

from typing import Any

import pytest

from shared.csrf import CSRF_COOKIE_NAME, CSRFError, verify_csrf


def _event(cookie_value: str | None, header_value: str | None) -> dict[str, Any]:
    cookies: list[str] = []
    headers: dict[str, str] = {}
    if cookie_value is not None:
        cookies.append(f"{CSRF_COOKIE_NAME}={cookie_value}")
    if header_value is not None:
        headers["x-csrf-token"] = header_value
    return {"cookies": cookies, "headers": headers}


def test_happy_path_matching_token() -> None:
    verify_csrf(_event("matching-token-abc123", "matching-token-abc123"))


def test_raises_when_cookie_missing() -> None:
    with pytest.raises(CSRFError, match="missing"):
        verify_csrf(_event(None, "some-header-value"))


def test_raises_when_header_missing() -> None:
    with pytest.raises(CSRFError, match="missing"):
        verify_csrf(_event("some-cookie-value", None))


def test_raises_when_tokens_mismatch() -> None:
    with pytest.raises(CSRFError, match="mismatch"):
        verify_csrf(_event("token-A", "token-B"))


def test_accepts_legacy_cased_header() -> None:
    event = {
        "cookies": [f"{CSRF_COOKIE_NAME}=tok"],
        "headers": {"X-CSRF-Token": "tok"},
    }
    verify_csrf(event)


def test_accepts_cookie_in_raw_header() -> None:
    """HTTP API v2 czasem nie populuje `cookies` array dla manual fetch'ów —
    parser musi też obejrzeć raw `cookie` header."""
    event = {
        "cookies": [],
        "headers": {
            "cookie": f"other=value; {CSRF_COOKIE_NAME}=raw-tok; trailing=x",
            "x-csrf-token": "raw-tok",
        },
    }
    verify_csrf(event)
