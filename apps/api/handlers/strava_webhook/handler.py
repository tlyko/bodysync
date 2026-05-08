"""GET + POST /api/strava/webhook — Strava push subscription endpoint.

Two flows behind one route:

1. **GET handshake** — Strava verifies subscription. Echo `hub.challenge`
   gdy `hub.verify_token` matchuje SSM secret (constant-time compare).

2. **POST event** — Strava pushes event JSON dla każdej activity create/
   update/delete. Identity check (subscription_id + owner_id w athlete map),
   idempotent PutItem do EVENT#strava (TTL 7d). DDB Stream trigger w Step 5
   wyciąga te events i invokuje fetcher.

Latency budget < 2s — Strava retry-uje po timeout. NIGDY nie logujemy
full payload (PII concern: athlete name, activity coordinates).
"""

from __future__ import annotations

import hmac
import json
from typing import Any

from pydantic import ValidationError

from shared.dynamo import put_item_idempotent
from shared.logging import get_logger
from shared.ssm import get_param
from shared.strava import (
    EVENT_TTL_SECONDS,
    SYNTHETIC_SUBSCRIPTION_ID,
    StravaWebhookEvent,
)

logger = get_logger("strava_webhook")

VERIFY_TOKEN_PARAM = "/bodysync/strava/verify_token"
SUBSCRIPTION_ID_PARAM = "/bodysync/strava/subscription_id"
ATHLETE_MAP_PARAM = "/bodysync/strava/athlete-to-user"


def _response(status: int, body: dict[str, Any] | str = "") -> dict[str, Any]:
    if isinstance(body, dict):
        return {
            "statusCode": status,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body),
        }
    return {
        "statusCode": status,
        "headers": {"Content-Type": "text/plain"},
        "body": body,
    }


def _athlete_map(refresh: bool = False) -> dict[str, str]:
    """Read athlete-to-user JSON map z SSM (cached). `refresh=True` invaliduje
    cache — używane przy unknown athlete miss (callback mógł właśnie napisać
    nowy entry).
    """
    if refresh:
        from shared import ssm as _ssm

        _ssm._cache.pop(ATHLETE_MAP_PARAM, None)
    raw = get_param(ATHLETE_MAP_PARAM, decrypt=False)
    try:
        m = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        logger.error("athlete_map_invalid_json")
        return {}
    return m if isinstance(m, dict) else {}


def handle_handshake(event: dict[str, Any]) -> dict[str, Any]:
    qs: dict[str, str] = event.get("queryStringParameters") or {}
    mode = qs.get("hub.mode")
    token = qs.get("hub.verify_token")
    challenge = qs.get("hub.challenge")

    if mode != "subscribe" or not token or not challenge:
        logger.warning("handshake_bad_params")
        return _response(400, "bad request")

    try:
        expected = get_param(VERIFY_TOKEN_PARAM)
    except Exception:
        logger.exception("verify_token_ssm_error")
        return _response(500, "ssm error")

    if expected == "PLACEHOLDER":
        logger.error("verify_token_placeholder")
        return _response(503, "verify_token not configured")

    # Constant-time compare — prevents timing oracle attacks na verify_token.
    if not hmac.compare_digest(token, expected):
        logger.warning("handshake_token_mismatch")
        return _response(403, "forbidden")

    logger.info("handshake_ok")
    return _response(200, {"hub.challenge": challenge})


def handle_event(event: dict[str, Any]) -> dict[str, Any]:
    raw_body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64

        raw_body = base64.b64decode(raw_body).decode("utf-8")

    # Malformed body → 200 (Strava nie retry-uje malformed; log warn).
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning("event_invalid_json")
        return _response(200, "ok")

    try:
        webhook_event = StravaWebhookEvent.model_validate(payload)
    except ValidationError:
        logger.warning("event_validation_failed")
        return _response(200, "ok")

    # Identity check — subscription_id + owner_id muszą matchować nasze.
    try:
        sub_id_raw = get_param(SUBSCRIPTION_ID_PARAM, decrypt=False)
    except Exception:
        logger.exception("subscription_id_ssm_error")
        return _response(200, "ok")

    try:
        real_sub_id = int(sub_id_raw)
    except (TypeError, ValueError):
        # PLACEHOLDER lub bad value — accept jakikolwiek subscription dopóki
        # owner nie odpali strava_subscribe.py CLI. Loguj warn ale nie blokuj
        # (głupie żebyśmy odrzucali własne testowe events).
        logger.warning(
            "subscription_id_unconfigured",
            extra={"reason": "ssm_placeholder"},
        )
        real_sub_id = -1

    if (
        webhook_event.subscription_id != real_sub_id
        and webhook_event.subscription_id != SYNTHETIC_SUBSCRIPTION_ID
    ):
        # Unknown subscription — drop silent (no oracle dla attacker).
        logger.warning(
            "event_unknown_subscription",
            extra={
                "received_sub": webhook_event.subscription_id,
            },
        )
        return _response(200, "ok")

    # Owner check — map athlete_id → bodysync user. Refresh cache raz przy miss
    # (nowy user właśnie OAuth'd w innym Lambda warm cache).
    athletes = _athlete_map()
    athlete_key = str(webhook_event.owner_id)
    if athlete_key not in athletes:
        athletes = _athlete_map(refresh=True)
        if athlete_key not in athletes:
            logger.warning(
                "event_unknown_owner",
                extra={"owner_id": webhook_event.owner_id},
            )
            return _response(200, "ok")

    user_id = athletes[athlete_key]

    # Idempotent write. PK=EVENT#strava, SK={sub}#{object}#{event_time} —
    # dwa eventy z tym samym (subscription, object, event_time) = duplikat
    # (Strava replay'uje przy timeout/network error).
    sk = f"{webhook_event.subscription_id}#{webhook_event.object_id}#{webhook_event.event_time}"
    try:
        written = put_item_idempotent(
            pk="EVENT#strava",
            sk=sk,
            attrs={
                "user_id": user_id,
                "owner_id": webhook_event.owner_id,
                "object_type": webhook_event.object_type,
                "object_id": webhook_event.object_id,
                "aspect_type": webhook_event.aspect_type,
                "event_time": webhook_event.event_time,
                "subscription_id": webhook_event.subscription_id,
                "ttl": webhook_event.event_time + EVENT_TTL_SECONDS,
            },
        )
    except Exception:
        # Don't burn Strava retry budget — log error, return 200.
        logger.exception(
            "event_ddb_error",
            extra={"user_id": user_id, "object_id": webhook_event.object_id},
        )
        return _response(200, "ok")

    logger.info(
        "strava_webhook_event",
        extra={
            "user_id": user_id,
            "object_id": webhook_event.object_id,
            "object_type": webhook_event.object_type,
            "aspect_type": webhook_event.aspect_type,
            "subscription_id": webhook_event.subscription_id,
            "duplicate": not written,
        },
    )
    return _response(200, "ok")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    method = (event.get("requestContext") or {}).get("http", {}).get("method", "")
    if method == "GET":
        return handle_handshake(event)
    if method == "POST":
        return handle_event(event)
    return _response(405, "method not allowed")
