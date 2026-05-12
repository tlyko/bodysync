"""AWS Lambda entrypoint dla POST /api/waitlist.

Public landing endpoint — bez JWT, bez Bearer. Zbiera email + opcjonalny
interest text + RODO consent. Anti-bot honeypot pole (hidden w UI), bot
fills → 200 silent (nie uczymy bota co poszło źle), human → 200 OK.

Layout response:
- 200 `{"ok": true}` — happy path + honeypot path (silent).
- 422 `{"error": "validation_failed", "fields": [...]}` — bad email,
  consent=False, interest > 500 chars. Sanityzowane do `loc + msg`
  (NIE `input` field z Pydantic — reflection vector dla XSS).
- 500 `{"error": "internal"}` — DDB write fail.

NIGDY nie loguje plain email — owner zobaczy fingerprint sha256[:16] dla
debugowania (czy ta sama osoba submittuje vs spam). IP też hashowane.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import ValidationError

from handlers.waitlist.schemas import WaitlistSignupRequest
from handlers.waitlist.service import save_signup
from shared.logging import get_logger

logger = get_logger("waitlist")


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _extract_ip(event: dict[str, Any]) -> str:
    """Wyciągnij IP z requestu.

    Priorytet:
    1. `X-Forwarded-For` pierwszy entry (CloudFront/CF inserts client IP).
       API Gateway HTTP v2 normalizuje header names do lowercase.
    2. `event['requestContext']['http']['sourceIp']` (API GW direct).
    3. `"unknown"` fallback — sanity, w prod zawsze będzie #2.
    """
    headers = event.get("headers") or {}
    xff = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
    if xff:
        # XFF może być listą "client, proxy1, proxy2" — bierzemy pierwszy.
        return xff.split(",", 1)[0].strip()
    source = (event.get("requestContext") or {}).get("http", {}).get("sourceIp")
    if source:
        return str(source)
    return "unknown"


def _extract_referrer(event: dict[str, Any]) -> str | None:
    """`Referer` (sic — RFC 7231 keeps the misspelling) header, case-insensitive."""
    headers = event.get("headers") or {}
    return headers.get("referer") or headers.get("Referer")


def _is_honeypot_error(err: ValidationError) -> bool:
    """Sprawdź czy ValidationError pochodzi z honeypot field_validator.

    Pydantic v2 wraps `ValueError("honeypot_filled")` w error z
    `type == "value_error"` i `msg == "Value error, honeypot_filled"`.
    Sprawdzamy `loc[0] == "honeypot"` żeby na pewno był to ten validator.
    """
    for e in err.errors():
        loc = e.get("loc") or ()
        if loc and loc[0] == "honeypot":
            return True
    return False


def _sanitize_validation_errors(err: ValidationError) -> list[dict[str, Any]]:
    """Zwróć listę `{loc, msg}` bez `input` field (reflection-safe).

    `msg` w Pydantic v2 jest format'owany jako "Value error, <raw>" dla
    custom validators — ujawniamy bo sami kontrolujemy stringi w schemas.py
    (`consent_required`, `honeypot_filled` — fixed vocabulary, NIE user input).
    Built-in errors (email syntax, max_length) też mają safe `msg`.
    """
    out: list[dict[str, Any]] = []
    for e in err.errors():
        out.append({"loc": list(e.get("loc") or ()), "msg": e.get("msg", "")})
    return out


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "local")

    raw_body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64

        raw_body = base64.b64decode(raw_body).decode("utf-8")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning("waitlist_invalid_json", extra={"request_id": request_id})
        return _response(422, {"error": "validation_failed", "fields": []})

    try:
        req = WaitlistSignupRequest.model_validate(payload)
    except ValidationError as e:
        if _is_honeypot_error(e):
            # Silent 200 — bot signal. Nie zapisujemy do DDB, nie uczymy
            # bota co poszło źle (404/422 reveals honeypot mechanism).
            logger.info(
                "waitlist_honeypot_triggered",
                extra={"request_id": request_id, "handler": "waitlist"},
            )
            return _response(200, {"ok": True})
        fields = _sanitize_validation_errors(e)
        logger.info(
            "waitlist_validation_failed",
            extra={"request_id": request_id, "handler": "waitlist"},
        )
        return _response(422, {"error": "validation_failed", "fields": fields})

    ip = _extract_ip(event)
    ip_hash = hashlib.sha256(ip.encode("utf-8")).hexdigest()
    referrer = _extract_referrer(event)
    email_hash = hashlib.sha256(req.email.lower().encode("utf-8")).hexdigest()

    try:
        save_signup(
            email=req.email,
            interest=req.interest,
            ip_hash=ip_hash,
            referrer=referrer,
            table_name=None,
        )
    except Exception:
        logger.exception(
            "waitlist_save_failed",
            extra={"request_id": request_id, "handler": "waitlist"},
        )
        return _response(500, {"error": "internal"})

    # Log fingerprint, NIE plain email/IP. 16 chars = 64 bits collision
    # space — owner widzi same-user resubmits, nie odzyskuje email'a.
    logger.info(
        "waitlist_signup",
        extra={
            "request_id": request_id,
            "handler": "waitlist",
            "email_hash": email_hash[:16],
            "ip_hash": ip_hash[:16],
            "has_interest": req.interest is not None and len(req.interest) > 0,
        },
    )
    return _response(200, {"ok": True})
