"""AWS Lambda dispatcher dla DELETE /api/me/account — RODO Art. 17 erasure.

Route: DELETE /api/me/account
Auth: JWT cookie `bodysync_session` + CSRF token + body `{"confirm": "DELETE"}`.

Cascade order w `service.erase_account`:
1. DDB rows pod `USER#{id z JWT}` (batch delete)
2. S3 raw payloads (HAE + Strava streams pod user prefix)
3. SSM per-user keys (Strava tokens, HAE webhook secret, training-sheet refs)
4. SSM athlete-to-user map (drop entries `value == user_id`)
5. SSM allowed_emails (drop entries `user_id == user_id`)

Response 200:
    {"deleted": {"ddb_rows": 4231, "s3_objects": 187, "ssm_user_keys": 4,
                 "athlete_map_entries": 1, "allowed_emails_entries": 1}}

Errors:
    401 — brak / invalid JWT cookie
    403 — brak / mismatch CSRF token
    422 — body brak / nie `{"confirm": "DELETE"}`
    500 — partial failure w cascade

PII: log `account_erased` z `user_id` + counts (NIE dane samych rows).

Lambda: 1024 MB / 29 s — pełna iteracja DDB partition + S3 paginated list.
"""

from __future__ import annotations

import json
from typing import Any

from botocore.exceptions import ClientError
from pydantic import ValidationError

from handlers.me_delete.schemas import DeleteAccountRequest
from handlers.me_delete.service import erase_account
from shared.auth import AuthError, verify_jwt
from shared.csrf import CSRFError, verify_csrf
from shared.http import extract_session_cookie, response
from shared.logging import get_logger

logger = get_logger("me_delete")


def _parse_json_body(event: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    raw_body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64

        raw_body = base64.b64decode(raw_body).decode("utf-8")
    try:
        return json.loads(raw_body), None
    except json.JSONDecodeError:
        return None, "invalid json body"


def handle(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point — DELETE /api/me/account."""
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

    try:
        verify_csrf(event)
    except CSRFError:
        logger.info("csrf_failed", extra={"request_id": request_id, "user_id": user_id})
        return response(403, {"error": "csrf_required"})

    parsed, err = _parse_json_body(event)
    if err is not None:
        return response(422, {"error": "validation_failed", "fields": [err]})

    try:
        DeleteAccountRequest.model_validate(parsed)
    except ValidationError as e:
        fields = [{"loc": list(err["loc"]), "type": err["type"]} for err in e.errors()]
        logger.info(
            "confirm_phrase_missing",
            extra={"request_id": request_id, "user_id": user_id},
        )
        return response(422, {"error": "validation_failed", "fields": fields})

    try:
        counts = erase_account(user_id)
    except ClientError:
        logger.exception(
            "cascade_failed",
            extra={"request_id": request_id, "user_id": user_id},
        )
        return response(500, {"error": "internal"})
    except Exception:
        logger.exception(
            "internal_error",
            extra={"request_id": request_id, "user_id": user_id},
        )
        return response(500, {"error": "internal"})

    logger.info(
        "account_erased",
        extra={
            "request_id": request_id,
            "user_id": user_id,
            **counts,
        },
    )
    return response(200, {"deleted": counts})
