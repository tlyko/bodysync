"""AWS Lambda dispatcher dla GET /api/me/export — GDPR Art. 20 data portability.

Route: GET /api/me/export
Auth: JWT cookie `bodysync_session` + CSRF token (defense-in-depth — eksport
      ujawnia ALL personal data, blokuje cross-site triggered downloads).

Response 200:
    Content-Type: application/json
    Content-Disposition: attachment; filename="bodysync-export-{user_id}-{date}.json"

    {
      "manifest": {"user_id", "generated_at", "row_count", "types": {...}},
      "rows": [...wszystkie DDB items pod USER#{id}...]
    }

Errors:
    401 — brak / invalid JWT cookie
    403 — brak / mismatch CSRF token
    500 — DDB Query fail

PII: structured log `export_generated` z `user_id` + `row_count` + `types`
(counts NIE values). Brak raw rows w logach per CLAUDE.md "NEVER log raw payloads".

Lambda: 1024 MB / 29 s (max API GW HTTP integration timeout). Pełny dump
typowo 1-2 MB JSON; query paginacja w `shared/dynamo.query_all_by_pk`.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from botocore.exceptions import ClientError

from handlers.me_export.service import build_export
from shared.auth import AuthError, verify_jwt
from shared.csrf import CSRFError, verify_csrf
from shared.http import extract_session_cookie, response
from shared.logging import get_logger

logger = get_logger("me_export")


def _attachment_response(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Buduje envelope z Content-Disposition attachment header."""
    filename = f"bodysync-export-{user_id}-{date.today().isoformat()}.json"
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
        "body": json.dumps(payload),
    }


def handle(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point — GET /api/me/export."""
    request_id = getattr(context, "aws_request_id", "local")

    token = extract_session_cookie(event)
    if not token:
        logger.info("missing_session", extra={"request_id": request_id})
        return response(401, {"error": "missing session cookie"})

    try:
        payload = verify_jwt(token)
    except AuthError as e:
        logger.info(
            "invalid_session",
            extra={"request_id": request_id, "reason": str(e)},
        )
        return response(401, {"error": "invalid session"})

    user_id = payload.get("user_id")
    if not user_id:
        return response(401, {"error": "user_id missing in jwt"})

    # CSRF guard (per AskUserQuestion 2026-05-17 — defense-in-depth dla
    # endpointu który ujawnia full personal data, mimo że GET nie zmienia
    # stanu).
    try:
        verify_csrf(event)
    except CSRFError:
        logger.info("csrf_failed", extra={"request_id": request_id, "user_id": user_id})
        return response(403, {"error": "csrf_required"})

    try:
        export = build_export(user_id)
    except ClientError:
        logger.exception(
            "ddb_query_failed",
            extra={"request_id": request_id, "user_id": user_id},
        )
        return response(500, {"error": "internal"})
    except Exception:
        logger.exception(
            "internal_error",
            extra={"request_id": request_id, "user_id": user_id},
        )
        return response(500, {"error": "internal"})

    manifest = export["manifest"]
    logger.info(
        "export_generated",
        extra={
            "request_id": request_id,
            "user_id": user_id,
            "row_count": manifest["row_count"],
            "types": manifest["types"],
        },
    )
    return _attachment_response(user_id, export)
