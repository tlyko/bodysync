"""AWS Lambda dispatcher dla profile targets endpointów.

Routes:
  GET /api/profile/targets   — bieżące cele kcal/makro (fallback defaults
                                gdy brak ustawionych)
  PUT /api/profile/targets   — body {kcal_target, protein_target_g,
                                fat_target_g, carbs_target_g} → merge do
                                PROFILE row

Auth: JWT cookie `bodysync_session`. Mirror api_read pattern.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from handlers.profile_targets.schemas import TargetsPayload, TargetsResponse
from handlers.profile_targets.service import (
    ProfileNotFoundError,
    get_targets,
    update_targets,
)
from shared.auth import AuthError, verify_jwt
from shared.logging import get_logger

logger = get_logger("profile_targets")

COOKIE_NAME = "bodysync_session"


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _extract_session_cookie(event: dict[str, Any]) -> str | None:
    cookies: list[str] = event.get("cookies") or []
    for cookie in cookies:
        if cookie.startswith(f"{COOKIE_NAME}="):
            return cookie.split("=", 1)[1]
    headers: dict[str, str] = event.get("headers") or {}
    raw: str | None = headers.get("cookie") or headers.get("Cookie")
    if raw:
        for part in raw.split(";"):
            stripped = part.strip()
            if stripped.startswith(f"{COOKIE_NAME}="):
                return stripped.split("=", 1)[1]
    return None


def _route_key(event: dict[str, Any]) -> str:
    return event.get("routeKey") or event.get("rawPath") or ""


def _http_method(event: dict[str, Any]) -> str:
    return (event.get("requestContext") or {}).get("http", {}).get("method", "")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "local")

    token = _extract_session_cookie(event)
    if not token:
        logger.info("missing_session", extra={"request_id": request_id})
        return _response(401, {"error": "missing session cookie"})

    try:
        payload = verify_jwt(token)
    except AuthError as e:
        logger.info(
            "invalid_session",
            extra={"request_id": request_id, "reason": str(e)},
        )
        return _response(401, {"error": "invalid session"})

    user_id = payload.get("user_id")
    if not user_id:
        return _response(401, {"error": "user_id missing in jwt"})

    method = _http_method(event)
    route = _route_key(event)

    try:
        if method == "GET":
            kcal, protein, fat, carbs, is_default = get_targets(user_id)
            body = TargetsResponse(
                kcal_target=kcal,
                protein_target_g=protein,
                fat_target_g=fat,
                carbs_target_g=carbs,
                is_default=is_default,
            )
            logger.info(
                "targets_get",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "is_default": is_default,
                },
            )
            return _response(200, body.model_dump())

        if method == "PUT":
            raw_body = event.get("body") or "{}"
            if event.get("isBase64Encoded"):
                import base64

                raw_body = base64.b64decode(raw_body).decode("utf-8")
            try:
                parsed = json.loads(raw_body)
            except json.JSONDecodeError:
                return _response(400, {"error": "invalid json body"})

            try:
                payload_obj = TargetsPayload.model_validate(parsed)
            except ValidationError as e:
                # Sanityzowane error details (loc + type, no input echo).
                sanitized = [{"loc": err["loc"], "type": err["type"]} for err in e.errors()]
                return _response(400, {"error": "invalid payload", "details": sanitized})

            update_targets(
                user_id,
                payload_obj.kcal_target,
                payload_obj.protein_target_g,
                payload_obj.fat_target_g,
                payload_obj.carbs_target_g,
            )
            response = TargetsResponse(
                kcal_target=payload_obj.kcal_target,
                protein_target_g=payload_obj.protein_target_g,
                fat_target_g=payload_obj.fat_target_g,
                carbs_target_g=payload_obj.carbs_target_g,
                is_default=False,
            )
            logger.info(
                "targets_put",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "kcal_target": payload_obj.kcal_target,
                    "protein_target_g": payload_obj.protein_target_g,
                },
            )
            return _response(200, response.model_dump())

        logger.warning(
            "method_not_allowed",
            extra={"request_id": request_id, "method": method, "route": route},
        )
        return _response(405, {"error": "method not allowed"})

    except ProfileNotFoundError:
        logger.warning(
            "profile_not_found",
            extra={"request_id": request_id, "user_id": user_id},
        )
        return _response(404, {"error": "profile not found"})
    except Exception:
        logger.exception("internal_error", extra={"request_id": request_id})
        return _response(500, {"error": "internal"})
