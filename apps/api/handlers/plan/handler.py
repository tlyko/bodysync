"""GET /api/plan — Google Sheets training plan, cached 15min w DDB.

Auth: JWT cookie `bodysync_session` (mirror profile_targets pattern).
Query params:
  - `refresh=1` — force-fetch z Sheets, bypass cache (UI button "odśwież")

Flow:
1. Validate JWT → user_id
2. Load SSM: service_account_json + per-user sheet_id + sheet_tab
3. Try cache (unless force_refresh):
   - hit + fresh (<15min) → return cached, fresh=False
4. Fetch fresh z Google Sheets API
5. Persist DDB cache
6. Return PlanResponse, fresh=True

Fallback: gdy Google API down + cache hit (stale) → return stale z fresh=False.
Owner widzi "ostatnio: 2h temu" i może kliknąć force-refresh later.
"""

from __future__ import annotations

import json
import time
from typing import Any

from handlers.plan.schemas import CachedPlan, PlanResponse
from handlers.plan.service import (
    PlanFetchError,
    fetch_sheet_values,
    is_fresh,
    load_cached_plan,
    save_cached_plan,
)
from shared.auth import AuthError, verify_jwt
from shared.logging import get_logger
from shared.ssm import get_param

logger = get_logger("plan")

COOKIE_NAME = "bodysync_session"

SERVICE_ACCOUNT_PARAM = "/bodysync/google/service_account_json"


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


def _force_refresh(event: dict[str, Any]) -> bool:
    qs = event.get("queryStringParameters") or {}
    raw = qs.get("refresh", "")
    return raw in ("1", "true", "yes")


def _sheet_id_param(user_id: str) -> str:
    return f"/bodysync/{user_id}/training-sheet-id"


def _sheet_tab_param(user_id: str) -> str:
    return f"/bodysync/{user_id}/training-sheet-tab"


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "local")

    # ─── Auth ──────────────────────────────────────────────────────────
    token = _extract_session_cookie(event)
    if not token:
        logger.info("missing_session", extra={"request_id": request_id})
        return _response(401, {"error": "missing session cookie"})
    try:
        payload = verify_jwt(token)
    except AuthError:
        logger.info("invalid_session", extra={"request_id": request_id})
        return _response(401, {"error": "invalid session"})
    user_id = payload.get("user_id")
    if not user_id:
        return _response(401, {"error": "user_id missing in jwt"})

    force = _force_refresh(event)

    # ─── Load config (SSM) ─────────────────────────────────────────────
    try:
        sheet_id = get_param(_sheet_id_param(user_id), decrypt=False)
        sheet_tab = get_param(_sheet_tab_param(user_id), decrypt=False)
        sa_json = get_param(SERVICE_ACCOUNT_PARAM, decrypt=True)
    except Exception:
        logger.exception(
            "ssm_config_error",
            extra={"request_id": request_id, "user_id": user_id},
        )
        return _response(503, {"error": "not_configured"})

    if sheet_id == "PLACEHOLDER" or sheet_tab == "PLACEHOLDER" or sa_json == "PLACEHOLDER":
        logger.warning(
            "ssm_placeholder",
            extra={"request_id": request_id, "user_id": user_id},
        )
        return _response(503, {"error": "not_configured"})

    # ─── Cache check ──────────────────────────────────────────────────
    cached = load_cached_plan(user_id)
    if not force and cached is not None and is_fresh(cached):
        logger.info(
            "plan_cache_hit",
            extra={
                "request_id": request_id,
                "user_id": user_id,
                "rows": len(cached.rows),
                "age_seconds": int(time.time()) - cached.fetched_at,
            },
        )
        return _response(
            200,
            PlanResponse(
                rows=cached.rows,
                fetched_at=cached.fetched_at,
                fresh=False,
                sheet_tab=cached.sheet_tab,
            ).model_dump(),
        )

    # ─── Fresh fetch z Google Sheets ──────────────────────────────────
    try:
        rows = fetch_sheet_values(sheet_id, sheet_tab, sa_json)
    except PlanFetchError as e:
        # Stale fallback: lepiej oddać 2-godzinny cache niż 503 jeśli
        # owner ma config OK ale Google chwilowo niedostępny.
        if cached is not None:
            logger.warning(
                "plan_fetch_failed_serving_stale",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "reason": e.reason,
                    "stale_age_seconds": int(time.time()) - cached.fetched_at,
                },
            )
            return _response(
                200,
                PlanResponse(
                    rows=cached.rows,
                    fetched_at=cached.fetched_at,
                    fresh=False,
                    sheet_tab=cached.sheet_tab,
                ).model_dump(),
            )
        logger.warning(
            "plan_fetch_failed_no_cache",
            extra={
                "request_id": request_id,
                "user_id": user_id,
                "reason": e.reason,
            },
        )
        # 503 dla config errors (credentials, permissions), 502 dla API down.
        status = (
            503
            if e.reason
            in (
                "invalid_credentials_json",
                "invalid_credentials_format",
                "permission_denied",
                "sheet_not_found_or_no_access",
            )
            else 502
        )
        return _response(status, {"error": e.reason})

    # ─── Persist cache + return ───────────────────────────────────────
    now = int(time.time())
    plan = CachedPlan(rows=rows, fetched_at=now, sheet_tab=sheet_tab)
    try:
        save_cached_plan(user_id, plan)
    except Exception:
        # Cache write failure NIE blokuje response — frontend dostanie
        # świeże dane, następny request po prostu refetcha.
        logger.exception(
            "cache_write_failed",
            extra={"request_id": request_id, "user_id": user_id},
        )

    logger.info(
        "plan_fetched",
        extra={
            "request_id": request_id,
            "user_id": user_id,
            "rows": len(rows),
            "force_refresh": force,
            "sheet_tab": sheet_tab,
        },
    )
    return _response(
        200,
        PlanResponse(
            rows=rows,
            fetched_at=now,
            fresh=True,
            sheet_tab=sheet_tab,
        ).model_dump(),
    )
