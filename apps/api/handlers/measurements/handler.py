"""AWS Lambda dispatcher dla POST /api/measurements — manual body tape pomiary.

Route: POST /api/measurements
Auth: JWT cookie `bodysync_session` (mirror profile_targets).

Request:
    {
      "date": "2026-05-14",
      "waist_cm": 85.5,
      "hips_cm": 98.0,
      "chest_cm": null,
      ...
    }

Response 200:
    {"saved": ["waist", "hips"], "date": "2026-05-14"}

Errors:
    401 — brak / invalid JWT cookie
    422 — validation error (invalid date, all-null, range violation)
    500 — DDB write fail

PII: structured log `measurements_saved` z `metrics_saved` (lista nazw, NIE
values — `85.5 cm waist` jest osobistą biometrią, nie loggujemy zgodnie
z CLAUDE.md "NEVER log raw payloads").
"""

from __future__ import annotations

import json
from typing import Any

from botocore.exceptions import ClientError
from pydantic import ValidationError

from handlers.measurements.schemas import MeasurementsRequest
from handlers.measurements.service import save_measurements
from shared.auth import AuthError, verify_jwt
from shared.csrf import CSRFError, verify_csrf
from shared.http import extract_session_cookie, response
from shared.logging import get_logger

logger = get_logger("measurements")


# Mapping z Pydantic field name → DDB SK metric segment. Strip `_cm` suffix
# żeby SK był `BIOMETRY#date#waist#manual` (nie `waist_cm#manual`) — krótsza
# klucze, dopasowane do reszty biometry (`#weight`, `#hrv`, `#sleep`).
_FIELD_TO_METRIC = {
    "waist_cm": "waist",
    "hips_cm": "hips",
    "chest_cm": "chest",
    "biceps_cm": "biceps",
    "thigh_cm": "thigh",
}


def _parse_json_body(event: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Return (parsed, error_msg). error_msg None gdy parse OK."""
    raw_body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64

        raw_body = base64.b64decode(raw_body).decode("utf-8")
    try:
        return json.loads(raw_body), None
    except json.JSONDecodeError:
        return None, "invalid json body"


def handle(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point — POST /api/measurements.

    JWT cookie auth → parse body → MeasurementsRequest → per-metric PutItem
    pod USER#{user_id z JWT}. PK isolation guaranteed by using JWT user_id
    (NIE z body) — defense in depth z IAM LeadingKeys=USER#* condition.
    """
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

    # CSRF guard (sec audit 2026-05-16 P1-4) — double-submit cookie.
    try:
        verify_csrf(event)
    except CSRFError:
        logger.info("csrf_failed", extra={"request_id": request_id, "user_id": user_id})
        return response(403, {"error": "csrf_required"})

    parsed, err = _parse_json_body(event)
    if err is not None:
        return response(422, {"error": "validation_failed", "fields": [err]})

    try:
        req = MeasurementsRequest.model_validate(parsed)
    except ValidationError as e:
        fields = [{"loc": list(err["loc"]), "type": err["type"]} for err in e.errors()]
        logger.info(
            "validation_failed",
            extra={"request_id": request_id, "user_id": user_id},
        )
        return response(422, {"error": "validation_failed", "fields": fields})

    # Strip `_cm` suffix + drop None values (Pydantic optional).
    measurements: dict[str, float] = {}
    for pyd_field, metric_name in _FIELD_TO_METRIC.items():
        value = getattr(req, pyd_field)
        if value is not None:
            measurements[metric_name] = value

    try:
        saved_map = save_measurements(user_id, req.date, measurements)
    except ClientError:
        logger.exception(
            "ddb_write_failed",
            extra={"request_id": request_id, "user_id": user_id},
        )
        return response(500, {"error": "internal"})
    except Exception:
        logger.exception(
            "internal_error",
            extra={"request_id": request_id, "user_id": user_id},
        )
        return response(500, {"error": "internal"})

    saved_list = sorted(saved_map.keys())
    logger.info(
        "measurements_saved",
        extra={
            "request_id": request_id,
            "user_id": user_id,
            # `metrics_saved` w shared/logging.py whitelist niżej dodajemy.
            # NIE values — biometria osobista, log retention 90d.
            "metrics_saved": saved_list,
            "date": req.date,
        },
    )
    return response(200, {"saved": saved_list, "date": req.date})
