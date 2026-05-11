"""AWS Lambda dispatcher dla adaptive TDEE recalc (Sprint 11 PR2/5).

Routes:
  POST /api/tdee/recalc — manual button (JWT). Recalc dla user_id z JWT,
                          persist tdee_adaptive + tdee_last_recalc + tdee_history.

EventBridge cron (PR3, `rate(14 days)`):
  Event shape: `{"users": ["tomek", "weronika"]}`. Iterate per user,
  per-user try/catch (error w jednym user nie blokuje drugiego).

Algorithm w `service.recalculate_tdee` (PR1, pure). Handler robi DDB I/O
+ JWT auth. Macros sync (kcal_target + protein/fat/carbs auto-update z
nowego TDEE) odłożony do PR4 — cross-handler change w
`profile_targets.update_targets()`.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from handlers.tdee_recalc.schemas import BiometryWindow, RecalcResult
from handlers.tdee_recalc.service import (
    WINDOW_DAYS,
    build_history_entry,
    cap_history,
    recalculate_tdee,
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
    """Zbierz raw weights + per-day kcal_in totals z last `WINDOW_DAYS`.

    `kcal_in` przez `sum_metric_in_range` (cumulative bucket'y per godzinę,
    sumowane per dzień). `weight` przez per-day GetItem (snapshot, no ts).
    """
    start = today - timedelta(days=WINDOW_DAYS)

    weights = query_weights_in_range(user_id, start, today)

    kcals_dict = sum_metric_in_range(user_id, "kcal_in", value_attr="value", start=start, end=today)
    kcals: list[tuple[date, int]] = []
    for d_iso, kcal_decimal in kcals_dict.items():
        kcal = int(kcal_decimal)
        if kcal > 0:
            kcals.append((date.fromisoformat(d_iso), kcal))

    return BiometryWindow(weights=weights, kcals=kcals)


def _persist_recalc(
    user_id: str,
    profile: dict[str, Any],
    result: RecalcResult,
    today: date,
) -> None:
    """Update PROFILE row z nowymi tdee_* attrs.

    PR2 minimal scope: `tdee_adaptive` (jeśli not skipped) +
    `tdee_last_recalc` (zawsze) + `tdee_history` (append + cap 20 FIFO).
    PR4 dodaje macro sync (kcal_target + 3 makro + body_profile_change reset).
    """
    history_raw = profile.get("tdee_history") or []
    history = [
        entry if hasattr(entry, "model_validate") else _parse_history_entry(entry)
        for entry in history_raw
    ]
    new_entry = build_history_entry(today=today, result=result)
    history.append(new_entry)
    history = cap_history(history)

    last_recalc_dump = new_entry.model_dump(mode="json")

    merged: dict[str, Any] = {**profile}
    if not result.skipped:
        merged["tdee_adaptive"] = result.tdee_after
    merged["tdee_last_recalc"] = last_recalc_dump
    merged["tdee_history"] = [h.model_dump(mode="json") for h in history]

    merged.pop("PK", None)
    merged.pop("SK", None)

    put_item(f"USER#{user_id}", "PROFILE", merged)


def _parse_history_entry(raw: Any) -> Any:
    """DDB stored history entries to dict (po deserializacji boto3).
    Validujemy z powrotem do RecalcHistoryEntry żeby cap_history dostała
    spójny typ. Lazy import w runtime — unika circular."""
    from handlers.tdee_recalc.schemas import RecalcHistoryEntry

    return RecalcHistoryEntry.model_validate(raw)


def _process_user(user_id: str, today: date) -> RecalcResult:
    """Read PROFILE → load window → recalculate → persist. Return result."""
    profile = get_item(f"USER#{user_id}", "PROFILE")
    if profile is None:
        raise ProfileNotFoundError(user_id)

    baseline_raw = profile.get("tdee_baseline")
    if baseline_raw is None:
        # Owner nie przeszedł przez TDEE wizard (PR4 inicjalizuje przy
        # first body_profile save). Skip + log + persist last_recalc
        # żeby UI mógł pokazać "wait, init body profile first".
        skipped = RecalcResult(
            ok=True,
            skipped=True,
            reason="baseline_not_initialized",
            tdee_before=0,
            tdee_after=0,
            kcal_in_avg=None,
            waga_delta_kg=None,
            adjustment=None,
            capped=False,
        )
        _persist_recalc(user_id, profile, skipped, today)
        return skipped

    baseline = int(baseline_raw)
    current_raw = profile.get("tdee_adaptive")
    current = int(current_raw) if current_raw is not None else baseline

    window = _load_window(user_id, today)
    result = recalculate_tdee(today=today, baseline=baseline, current=current, window=window)
    _persist_recalc(user_id, profile, result, today)
    return result


def _handle_cron(event: dict[str, Any], request_id: str, today: date) -> dict[str, Any]:
    """EventBridge cron — iterate per user z `event["users"]`.

    Per-user try/catch — error w jednym nie blokuje drugiego. Aggregate
    log line `tdee_recalc_cron_complete` dla CloudWatch metric/alarm.
    """
    users: list[str] = list(event["users"])
    recalculated = 0
    skipped = 0
    errored = 0

    for user_id in users:
        try:
            result = _process_user(user_id, today)
            if result.skipped:
                skipped += 1
            else:
                recalculated += 1
        except Exception:
            logger.exception(
                "tdee_recalc_user_failed",
                extra={"request_id": request_id, "user_id": user_id},
            )
            errored += 1

    summary = {
        "users": len(users),
        "recalculated": recalculated,
        "skipped": skipped,
        "errored": errored,
    }
    logger.info(
        "tdee_recalc_cron_complete",
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
            "tdee_recalc_failed",
            extra={"request_id": request_id, "user_id": user_id},
        )
        return _response(500, {"error": "internal"})

    logger.info(
        "tdee_recalc_complete",
        extra={
            "request_id": request_id,
            "user_id": user_id,
            "skipped": result.skipped,
            "reason": result.reason,
            "tdee_before": result.tdee_before,
            "tdee_after": result.tdee_after,
            "adjustment": result.adjustment,
        },
    )
    return _response(200, result.model_dump(mode="json"))
