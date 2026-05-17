"""AWS Lambda dispatcher dla profile targets endpointów.

Routes:
  GET  /api/profile/targets        — bieżące cele kcal/makro + opcjonalny body_profile
  PUT  /api/profile/targets        — body {kcal, protein, fat, carbs, body_profile?}
                                      → merge do PROFILE row
  POST /api/profile/calculate-tdee — input body_profile + opcjonalny weight_kg,
                                      output proposed targets (NIE persisted —
                                      frontend pokazuje user, on PUT-uje)

Auth: JWT cookie `bodysync_session`. Mirror api_read pattern.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from handlers.profile_targets.schemas import (
    CalculateTDEERequest,
    CalculateTDEEResponse,
    TargetsPayload,
    TargetsResponse,
)
from handlers.profile_targets.service import (
    ProfileNotFoundError,
    WeightNotFoundError,
    calculate_bmr,
    calculate_target_kcal,
    calculate_tdee,
    get_latest_weight_kg,
    get_targets,
    get_tdee_state,
    suggest_macros,
    update_targets,
)
from shared.auth import AuthError, verify_jwt
from shared.csrf import CSRFError, verify_csrf
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
    method = (event.get("requestContext") or {}).get("http", {}).get("method", "")
    return str(method)


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
    raw_path = event.get("rawPath") or ""

    # CSRF guard dla non-safe methods (sec audit 2026-05-16 P1-4).
    if method not in {"GET", "HEAD", "OPTIONS"}:
        try:
            verify_csrf(event)
        except CSRFError:
            logger.info("csrf_failed", extra={"request_id": request_id, "user_id": user_id})
            return _response(403, {"error": "csrf_required"})

    try:
        # Route dispatch — calculate-tdee jest specyficzny path, separate od targets.
        if method == "POST" and "calculate-tdee" in raw_path:
            return _handle_calculate_tdee(event, user_id, request_id)

        if method == "GET":
            return _handle_get_targets(user_id, request_id)

        if method == "PUT":
            return _handle_put_targets(event, user_id, request_id)

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
    except WeightNotFoundError:
        logger.warning(
            "weight_not_found",
            extra={"request_id": request_id, "user_id": user_id},
        )
        return _response(
            400,
            {
                "error": "weight_not_found",
                "details": "no weight in BIOMETRY (last 100 items); pass weight_kg in payload",
            },
        )
    except Exception:
        logger.exception("internal_error", extra={"request_id": request_id})
        return _response(500, {"error": "internal"})


def _handle_get_targets(user_id: str, request_id: str) -> dict[str, Any]:
    kcal, protein, fat, carbs, is_default, body_profile = get_targets(user_id)
    tdee_state = get_tdee_state(user_id)
    body = TargetsResponse(
        kcal_target=kcal,
        protein_target_g=protein,
        fat_target_g=fat,
        carbs_target_g=carbs,
        is_default=is_default,
        body_profile=body_profile,
        tdee_baseline=tdee_state["tdee_baseline"],
        tdee_adaptive=tdee_state["tdee_adaptive"],
        tdee_last_recalc=tdee_state["tdee_last_recalc"],
        tdee_history=tdee_state["tdee_history"],
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


def _handle_put_targets(event: dict[str, Any], user_id: str, request_id: str) -> dict[str, Any]:
    parsed, err = _parse_json_body(event)
    if err is not None:
        return _response(400, {"error": err})

    try:
        payload_obj = TargetsPayload.model_validate(parsed)
    except ValidationError as e:
        sanitized = [{"loc": err["loc"], "type": err["type"]} for err in e.errors()]
        return _response(400, {"error": "invalid payload", "details": sanitized})

    update_targets(
        user_id,
        payload_obj.kcal_target,
        payload_obj.protein_target_g,
        payload_obj.fat_target_g,
        payload_obj.carbs_target_g,
        body_profile=payload_obj.body_profile,
    )
    # Re-read po update — body_profile init/change w `update_targets` może
    # override user-provided makro (auto-sync z nowego TDEE baseline). Response
    # musi reflect actual saved values, nie request payload.
    kcal, protein, fat, carbs, _is_default, body_profile_saved = get_targets(user_id)
    tdee_state = get_tdee_state(user_id)
    response = TargetsResponse(
        kcal_target=kcal,
        protein_target_g=protein,
        fat_target_g=fat,
        carbs_target_g=carbs,
        is_default=False,
        body_profile=body_profile_saved,
        tdee_baseline=tdee_state["tdee_baseline"],
        tdee_adaptive=tdee_state["tdee_adaptive"],
        tdee_last_recalc=tdee_state["tdee_last_recalc"],
        tdee_history=tdee_state["tdee_history"],
    )
    logger.info(
        "targets_put",
        extra={
            "request_id": request_id,
            "user_id": user_id,
            "kcal_target": payload_obj.kcal_target,
            "protein_target_g": payload_obj.protein_target_g,
            "has_body_profile": payload_obj.body_profile is not None,
        },
    )
    return _response(200, response.model_dump())


def _handle_calculate_tdee(event: dict[str, Any], user_id: str, request_id: str) -> dict[str, Any]:
    """Input BodyProfile (lub czyta z PROFILE) + waga (lub latest z BIOMETRY)
    → output proposed targets. NIE persistuje — frontend pokazuje user, on
    PUT-uje TargetsPayload z body_profile + 4 makro.
    """
    parsed, err = _parse_json_body(event)
    if err is not None:
        return _response(400, {"error": err})

    try:
        req = CalculateTDEERequest.model_validate(parsed)
    except ValidationError as e:
        sanitized = [{"loc": err["loc"], "type": err["type"]} for err in e.errors()]
        return _response(400, {"error": "invalid payload", "details": sanitized})

    # Body profile: payload override > zapisany w PROFILE > 400.
    body_profile = req.body_profile
    if body_profile is None:
        try:
            _, _, _, _, _, stored = get_targets(user_id)
        except ProfileNotFoundError:
            return _response(404, {"error": "profile not found"})
        if stored is None:
            return _response(
                400,
                {
                    "error": "body_profile_required",
                    "details": "body_profile must be provided when not yet saved",
                },
            )
        body_profile = stored

    # Waga: payload override > latest z BIOMETRY > 400.
    weight_kg = req.weight_kg
    if weight_kg is None:
        weight_kg = get_latest_weight_kg(user_id)
        if weight_kg is None:
            raise WeightNotFoundError(user_id)

    bmr = calculate_bmr(weight_kg, body_profile.height_cm, body_profile.age, body_profile.sex)
    tdee = calculate_tdee(bmr, body_profile.activity_level)
    target_kcal = calculate_target_kcal(tdee, body_profile.goal)
    protein_g, fat_g, carbs_g = suggest_macros(weight_kg, target_kcal)

    response = CalculateTDEEResponse(
        bmr=int(round(bmr)),
        tdee_maintenance=int(round(tdee)),
        target_kcal=target_kcal,
        target_protein_g=protein_g,
        target_fat_g=fat_g,
        target_carbs_g=carbs_g,
        weight_kg_used=round(weight_kg, 1),
    )
    logger.info(
        "tdee_calculated",
        extra={
            "request_id": request_id,
            "user_id": user_id,
            "bmr": int(round(bmr)),
            "tdee_maintenance": int(round(tdee)),
            "target_kcal": target_kcal,
        },
    )
    return _response(200, response.model_dump())
