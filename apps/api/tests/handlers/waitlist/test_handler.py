"""Tests dla handlers.waitlist (Sprint 12 PR1 — landing signup).

Coverage:
- happy path (no interest) → 200 + DDB row
- happy path z interest → DDB attrs.interest matches
- invalid email → 422
- consent=False → 422
- honeypot filled → 200 SILENTLY + brak DDB row
- interest > 500 chars → 422
- DDB write fail → 500
- IP hashing correct (X-Forwarded-For + sourceIp fallback)
- referrer captured
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from unittest.mock import patch


def _event(
    body: dict[str, Any] | str | None,
    *,
    source_ip: str = "203.0.113.5",
    xff: str | None = None,
    referer: str | None = None,
) -> dict[str, Any]:
    if body is None:
        raw = ""
    elif isinstance(body, str):
        raw = body
    else:
        raw = json.dumps(body)
    headers: dict[str, str] = {"content-type": "application/json"}
    if xff is not None:
        headers["x-forwarded-for"] = xff
    if referer is not None:
        headers["referer"] = referer
    return {
        "version": "2.0",
        "routeKey": "POST /api/waitlist",
        "rawPath": "/api/waitlist",
        "requestContext": {"http": {"method": "POST", "sourceIp": source_ip}},
        "headers": headers,
        "body": raw,
        "isBase64Encoded": False,
    }


class _FakeContext:
    aws_request_id = "test-req-id"


def _waitlist_items(table: Any) -> list[dict[str, Any]]:
    """Query wszystkie items pod PK=WAITLIST."""
    return list(
        table.query(
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={":pk": "WAITLIST"},
        )["Items"]
    )


# ─── happy path ────────────────────────────────────────────────────────────


def test_handler_happy_path_no_interest_returns_200_and_writes_ddb(
    dynamodb_table: Any,
) -> None:
    from handlers.waitlist import handler as h

    result = h.handler(
        _event({"email": "alice@example.com", "consent": True}),
        _FakeContext(),
    )

    assert result["statusCode"] == 200
    assert json.loads(result["body"]) == {"ok": True}

    items = _waitlist_items(dynamodb_table)
    assert len(items) == 1
    item = items[0]
    assert item["PK"] == "WAITLIST"
    assert item["email"] == "alice@example.com"
    assert item["interest"] is None
    # ip_hash sha256(203.0.113.5)
    expected_ip_hash = hashlib.sha256(b"203.0.113.5").hexdigest()
    assert item["ip_hash"] == expected_ip_hash
    assert item["referrer"] is None
    assert isinstance(int(item["created_at"]), int)


def test_handler_happy_path_with_interest_persists_text(dynamodb_table: Any) -> None:
    from handlers.waitlist import handler as h

    result = h.handler(
        _event(
            {
                "email": "Bob@Example.COM",  # mixed case — service lowercases
                "consent": True,
                "interest": "chcę dashboard dla mojej żony",
            },
            referer="https://bodysync.pl/",
        ),
        _FakeContext(),
    )

    assert result["statusCode"] == 200
    items = _waitlist_items(dynamodb_table)
    assert len(items) == 1
    item = items[0]
    # Email lowercased w storage
    assert item["email"] == "bob@example.com"
    assert item["interest"] == "chcę dashboard dla mojej żony"
    assert item["referrer"] == "https://bodysync.pl/"
    # SK format: {iso_ts}#{email_lower}
    assert item["SK"].endswith("#bob@example.com")


# ─── validation ────────────────────────────────────────────────────────────


def test_handler_invalid_email_returns_422(dynamodb_table: Any) -> None:
    from handlers.waitlist import handler as h

    result = h.handler(
        _event({"email": "notanemail", "consent": True}),
        _FakeContext(),
    )

    assert result["statusCode"] == 422
    body = json.loads(result["body"])
    assert body["error"] == "validation_failed"
    locs = [tuple(f["loc"]) for f in body["fields"]]
    assert ("email",) in locs
    assert _waitlist_items(dynamodb_table) == []


def test_handler_missing_consent_returns_422(dynamodb_table: Any) -> None:
    from handlers.waitlist import handler as h

    result = h.handler(
        _event({"email": "alice@example.com", "consent": False}),
        _FakeContext(),
    )

    assert result["statusCode"] == 422
    body = json.loads(result["body"])
    locs = [tuple(f["loc"]) for f in body["fields"]]
    assert ("consent",) in locs
    assert _waitlist_items(dynamodb_table) == []


def test_handler_interest_too_long_returns_422(dynamodb_table: Any) -> None:
    from handlers.waitlist import handler as h

    result = h.handler(
        _event(
            {
                "email": "alice@example.com",
                "consent": True,
                "interest": "x" * 501,
            }
        ),
        _FakeContext(),
    )

    assert result["statusCode"] == 422
    body = json.loads(result["body"])
    locs = [tuple(f["loc"]) for f in body["fields"]]
    assert ("interest",) in locs
    assert _waitlist_items(dynamodb_table) == []


# ─── honeypot (silent 200) ─────────────────────────────────────────────────


def test_handler_honeypot_filled_returns_200_silently_no_ddb(
    dynamodb_table: Any,
) -> None:
    """Bot signal — 200 OK aby nie odsłaniać honeypot mechanism, ale NIE
    zapisuje rzędu w DDB.
    """
    from handlers.waitlist import handler as h

    result = h.handler(
        _event(
            {
                "email": "spambot@example.com",
                "consent": True,
                "honeypot": "I am a bot",
            }
        ),
        _FakeContext(),
    )

    assert result["statusCode"] == 200
    assert json.loads(result["body"]) == {"ok": True}
    assert _waitlist_items(dynamodb_table) == []


# ─── error paths ───────────────────────────────────────────────────────────


def test_handler_invalid_json_returns_422(dynamodb_table: Any) -> None:
    from handlers.waitlist import handler as h

    bad = _event(None)
    bad["body"] = "{not json"
    result = h.handler(bad, _FakeContext())

    assert result["statusCode"] == 422
    assert _waitlist_items(dynamodb_table) == []


def test_handler_ddb_write_fail_returns_500(dynamodb_table: Any) -> None:
    """`save_signup` raises → handler logs `exception` + zwraca 500."""
    from handlers.waitlist import handler as h

    with patch("handlers.waitlist.handler.save_signup", side_effect=RuntimeError("ddb down")):
        result = h.handler(
            _event({"email": "alice@example.com", "consent": True}),
            _FakeContext(),
        )

    assert result["statusCode"] == 500
    assert json.loads(result["body"]) == {"error": "internal"}


# ─── IP extraction ─────────────────────────────────────────────────────────


def test_handler_uses_xff_when_present(dynamodb_table: Any) -> None:
    """X-Forwarded-For ma precedencję nad sourceIp (CF/CloudFront proxy)."""
    from handlers.waitlist import handler as h

    result = h.handler(
        _event(
            {"email": "alice@example.com", "consent": True},
            source_ip="10.0.0.1",  # internal proxy — ignored
            xff="198.51.100.42, 10.0.0.1",
        ),
        _FakeContext(),
    )

    assert result["statusCode"] == 200
    item = _waitlist_items(dynamodb_table)[0]
    expected = hashlib.sha256(b"198.51.100.42").hexdigest()
    assert item["ip_hash"] == expected


# ─── PK isolation ──────────────────────────────────────────────────────────


def test_handler_writes_only_to_waitlist_pk(dynamodb_table: Any) -> None:
    """Waitlist signup NIE pollutuje USER#* PK space — defense in depth.

    Smoke: po signupie zapytajmy oba PK i sprawdźmy że WAITLIST ma 1, a
    USER#anything ma 0 (NIE ma żadnego cross-write).
    """
    from handlers.waitlist import handler as h

    h.handler(
        _event({"email": "alice@example.com", "consent": True}),
        _FakeContext(),
    )

    user_items = list(
        dynamodb_table.query(
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={":pk": "USER#alice"},
        )["Items"]
    )
    waitlist_items = _waitlist_items(dynamodb_table)
    assert len(waitlist_items) == 1
    assert user_items == []
