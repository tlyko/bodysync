"""AWS Lambda dispatcher dla diet check / progress narrative (Sprint 11.5 ADR-009).

Routes:
  POST /api/tdee/recalc — manual button "Sprawdź teraz" (JWT). Reuse path
                          z PR2 Sprint 11 — frontend types refactored w PR2
                          Sprint 11.5 (drop RecalcResult, use DietCheckResult).

EventBridge cron `rate(14 days)`:
  Event shape: `{"users": ["tomek", "weronika"]}`. Iterate per user.
  Per ADR-009 sec 6 — log only (no Telegram push, defer enable).

Algorithm w `service.evaluate_diet_check` (pure). Handler robi DDB I/O +
JWT auth + persist `diet_check_history` (cap 10 FIFO). LLM narrative call
wyłączony w PR1 — `narrative` zawsze None, frontend pokazuje raw status
+ "Szczegóły" expansion. PR2 dorzuci LLM Haiku.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from handlers.tdee_recalc.schemas import (
    BiometryWindow,
    DietCheckHistoryEntry,
    DietCheckResult,
)
from handlers.tdee_recalc.service import (
    WINDOW_DAYS,
    build_diet_check_history_entry,
    cap_diet_check_history,
    evaluate_diet_check,
)
from shared.auth import AuthError, verify_jwt
from shared.dynamo import (
    get_item,
    put_item,
    query_weights_in_range,
    sum_metric_in_range,
)
from shared.logging import get_logger

logger = get_logger("tdee_recalc")

COOKIE_NAME = "bodysync_session"

# Hardcoded per CLAUDE.md "user scope dziś 2 userów". Multi-user dynamic
# wymagałby USER list entity albo Cognito — YAGNI.
CRON_USER_LIST = ["tomek", "weronika"]


class ProfileNotFoundError(Exception):
    """PROFILE row brak — handler zwraca 404."""


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
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


def _is_cron_event(event: dict[str, Any]) -> bool:
    """EventBridge cron event ma `users: list[str]`. HTTP event ma
    `requestContext.http`. Klucz `users` nie kollizuje z API GW shape."""
    return isinstance(event.get("users"), list)


def _load_window(user_id: str, today: date) -> BiometryWindow:
    """Zbierz raw weights + per-day kcal_in totals z last `WINDOW_DAYS`."""
    start = today - timedelta(days=WINDOW_DAYS)

    weights = query_weights_in_range(user_id, start, today)

    kcals_dict = sum_metric_in_range(user_id, "kcal_in", value_attr="value", start=start, end=today)
    kcals: list[tuple[date, int]] = []
    for d_iso, kcal_decimal in kcals_dict.items():
        kcal = int(kcal_decimal)
        if kcal > 0:
            kcals.append((date.fromisoformat(d_iso), kcal))

    return BiometryWindow(weights=weights, kcals=kcals)


def _persist_diet_check(
    user_id: str,
    profile: dict[str, Any],
    result: DietCheckResult,
    today: date,
) -> None:
    """Update PROFILE row z nowym `diet_check_history` entry (FIFO 10).

    PR1 minimal: tylko append history + last entry pointer. PR2 dorzuci
    LLM narrative (już wstrzykuje się przez `result.narrative` jeśli LLM
    został wywołany przed persist).

    Stare attrs (`tdee_baseline`, `tdee_adaptive`, `tdee_last_recalc`,
    `tdee_history`) zostają w PROFILE jako dead weight per ADR-009 sec 9
    (no migration). Pydantic ignoruje extra fields.
    """
    history_raw = profile.get("diet_check_history") or []
    history: list[DietCheckHistoryEntry] = [_parse_history_entry(e) for e in history_raw]
    new_entry = build_diet_check_history_entry(today=today, result=result)
    history.append(new_entry)
    history = cap_diet_check_history(history)

    last_entry_dump = new_entry.model_dump(mode="json")

    merged: dict[str, Any] = {**profile}
    merged["diet_check_last"] = last_entry_dump
    merged["diet_check_history"] = [h.model_dump(mode="json") for h in history]

    merged.pop("PK", None)
    merged.pop("SK", None)

    put_item(f"USER#{user_id}", "PROFILE", merged)


def _parse_history_entry(raw: Any) -> DietCheckHistoryEntry:
    """DDB stored history entries → Pydantic. Lazy import unika circular."""
    return DietCheckHistoryEntry.model_validate(raw)


def _process_user(user_id: str, today: date) -> DietCheckResult:
    """Read PROFILE → load window → evaluate → persist. Return result."""
    profile = get_item(f"USER#{user_id}", "PROFILE")
    if profile is None:
        raise ProfileNotFoundError(user_id)

    kcal_target_raw = profile.get("kcal_target")
    kcal_target = int(kcal_target_raw) if kcal_target_raw is not None else None

    window = _load_window(user_id, today)
    result = evaluate_diet_check(today=today, kcal_target=kcal_target, window=window)
    _persist_diet_check(user_id, profile, result, today)
    return result


def _handle_cron(event: dict[str, Any], request_id: str, today: date) -> dict[str, Any]:
    """EventBridge cron — iterate per user, per-user try/catch.

    Per ADR-009 sec 6 — log only. Aggregate `diet_check_cron_complete`
    line dla CloudWatch metric.
    """
    users: list[str] = list(event["users"])
    evaluated = 0
    skipped = 0
    errored = 0

    for user_id in users:
        try:
            result = _process_user(user_id, today)
            if result.skipped:
                skipped += 1
            else:
                evaluated += 1
        except Exception:
            logger.exception(
                "diet_check_user_failed",
                extra={"request_id": request_id, "user_id": user_id},
            )
            errored += 1

    summary = {
        "users": len(users),
        "evaluated": evaluated,
        "skipped": skipped,
        "errored": errored,
    }
    logger.info(
        "diet_check_cron_complete",
        extra={"request_id": request_id, **summary},
    )
    return summary


def _today_factory() -> date:
    """Indirection dla monkey-patch w testach (replace `date.today()`)."""
    return date.today()


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "local")
    today = _today_factory()

    if _is_cron_event(event):
        return _handle_cron(event, request_id, today)

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

    try:
        result = _process_user(user_id, today)
    except ProfileNotFoundError:
        logger.warning(
            "profile_not_found",
            extra={"request_id": request_id, "user_id": user_id},
        )
        return _response(404, {"error": "profile not found"})
    except Exception:
        logger.exception(
            "diet_check_failed",
            extra={"request_id": request_id, "user_id": user_id},
        )
        return _response(500, {"error": "internal"})

    logger.info(
        "diet_check_complete",
        extra={
            "request_id": request_id,
            "user_id": user_id,
            "skipped": result.skipped,
            "reason": result.skip_reason,
            "status": result.status,
        },
    )
    return _response(200, result.model_dump(mode="json"))
