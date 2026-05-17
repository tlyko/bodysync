"""AWS Lambda dispatcher dla POST /api/workouts/extract.

Route: POST /api/workouts/extract
Auth: JWT cookie `bodysync_session` + CSRF token.

Request body:
    {
      "today_iso": "2026-05-17",
      "trainings": [<Training[] z apps/web/src/components/dashboard/planParser.ts>]
    }

Response 200:
    {"extracted": N, "skipped": M, "errors": K, "items": [...]}
"""

from __future__ import annotations

import json
from typing import Any

from botocore.exceptions import ClientError
from pydantic import ValidationError

from handlers.workouts_extract.schemas import ExtractRequest, ExtractResponse
from handlers.workouts_extract.service import run_extract
from shared.auth import AuthError, verify_jwt
from shared.csrf import CSRFError, verify_csrf
from shared.http import extract_session_cookie, response
from shared.logging import get_logger

logger = get_logger("workouts_extract")


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
    request_id = getattr(context, "aws_request_id", "local")

    token = extract_session_cookie(event)
    if not token:
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
        return response(403, {"error": "csrf_required"})

    parsed, err = _parse_json_body(event)
    if err is not None:
        return response(422, {"error": "validation_failed", "fields": [err]})

    try:
        req = ExtractRequest.model_validate(parsed)
    except ValidationError as e:
        fields = [{"loc": list(err["loc"]), "type": err["type"]} for err in e.errors()]
        logger.info(
            "validation_failed",
            extra={"request_id": request_id, "user_id": user_id},
        )
        return response(422, {"error": "validation_failed", "fields": fields})

    try:
        items, skipped, errors = run_extract(
            user_id,
            today_iso=req.today_iso,
            trainings=req.trainings,
        )
    except ClientError:
        logger.exception(
            "ddb_failed",
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
        "extract_done",
        extra={
            "request_id": request_id,
            "user_id": user_id,
            "extracted": len(items),
            "skipped": skipped,
            "errors": errors,
        },
    )
    return response(
        200,
        ExtractResponse(
            extracted=len(items),
            skipped=skipped,
            errors=errors,
            items=items,
        ).model_dump(),
    )
