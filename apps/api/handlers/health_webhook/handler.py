"""AWS Lambda entrypoint dla POST /api/health/webhook.

Handler zachowuje krok do kroku per spec Sprint 3:
1. Wyciągnij Authorization Bearer (case-insensitive — API GW v2 normalizuje).
2. Resolve user_id po `hmac.compare_digest` z SSM secrets per user.
3. Parse JSON body → Pydantic HAEPayload (400 dla błędów).
4. service.ingest(user_id, payload) → IngestResult.
5. 200 z `{"received", "stored", "skipped_unknown"}`.

KEY INVARIANT: handler zwraca 200 dla wszystkich payload-level błędów
(w tym pojedyncze bad points). 4xx tylko dla auth (401), niesparsowalnego
body (400) i top-level Pydantic ValidationError (400). Zapobiega retry
storm gdy HAE wyśle batch z 1 zepsutym point'em.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from handlers.health_webhook.schemas import HAEPayload
from handlers.health_webhook.service import (
    AuthFailedError,
    ingest,
    resolve_user_from_bearer,
)
from shared.logging import get_logger

logger = get_logger("health_webhook")


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _extract_bearer(event: dict[str, Any]) -> str | None:
    """API Gateway HTTP API v2 normalizuje header names do lowercase."""
    headers = event.get("headers") or {}
    auth: str | None = headers.get("authorization") or headers.get("Authorization")
    if not auth:
        return None
    parts = auth.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "local")

    bearer = _extract_bearer(event)
    if not bearer:
        logger.warning("missing_auth", extra={"request_id": request_id})
        return _response(401, {"error": "missing or malformed Authorization header"})

    try:
        user_id = resolve_user_from_bearer(bearer)
    except AuthFailedError:
        logger.warning("invalid_bearer", extra={"request_id": request_id})
        return _response(401, {"error": "invalid bearer token"})

    raw_body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64

        raw_body = base64.b64decode(raw_body).decode("utf-8")

    try:
        payload_dict = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning("invalid_json", extra={"request_id": request_id, "user_id": user_id})
        return _response(400, {"error": "invalid json body"})

    try:
        payload = HAEPayload.model_validate(payload_dict)
    except ValidationError as e:
        # Sec audit C2 — sanityzujemy do loc+type, bez `input` field
        # (Pydantic `errors()` zawiera surowy user input).
        sanitized = [{"loc": err["loc"], "type": err["type"]} for err in e.errors()]
        logger.warning("invalid_payload", extra={"request_id": request_id, "user_id": user_id})
        return _response(400, {"error": "invalid payload", "details": sanitized})

    result = ingest(user_id, payload, ingested_at=datetime.now(UTC))
    logger.info(
        "hae_ingest_ok",
        extra={
            "request_id": request_id,
            "user_id": user_id,
            "received": result.received,
            "stored": result.stored,
            "skipped_unknown": result.skipped_unknown,
        },
    )
    return _response(
        200,
        {
            "received": result.received,
            "stored": result.stored,
            "skipped_unknown": result.skipped_unknown,
        },
    )
