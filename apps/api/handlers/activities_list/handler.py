"""GET /api/activities — lista aktywności bieżącego usera.

Query params:
- `limit` (int 1..50, default 10) — ile ostatnich activities
- `days` (int 1..365, default 30) — filtr czasowy (opcjonalny — nie ograniczamy
  twardo, tylko klient może obliczyć "ostatnie N dni" jako count limit)

Response: `{items: [...]}` z najnowszymi activities (descending start_date).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from shared.auth import AuthError, verify_jwt
from shared.dynamo import query_by_pk
from shared.logging import get_logger

logger = get_logger("activities_list")

COOKIE_NAME = "bodysync_session"
DEFAULT_LIMIT = 10
MAX_LIMIT = 50


def _decimal_safe(value: Any) -> Any:
    """JSON dump — boto3 zwraca Decimal dla N attributes."""
    if isinstance(value, Decimal):
        return float(value) if value % 1 != 0 else int(value)
    return value


def _response(status: int, body: dict[str, Any] | list[Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=_decimal_safe),
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


def _parse_limit(qs: dict[str, str]) -> int:
    raw = qs.get("limit")
    if not raw:
        return DEFAULT_LIMIT
    try:
        return max(1, min(MAX_LIMIT, int(raw)))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "local")

    token = _extract_session_cookie(event)
    if not token:
        return _response(401, {"error": "missing session cookie"})

    try:
        payload = verify_jwt(token)
    except AuthError:
        return _response(401, {"error": "invalid session"})

    user_id = payload.get("user_id")
    if not user_id:
        return _response(401, {"error": "user_id missing in jwt"})

    qs: dict[str, str] = event.get("queryStringParameters") or {}
    limit = _parse_limit(qs)

    rows = query_by_pk(f"USER#{user_id}", sk_prefix="ACTIVITY#")

    # Sort descending po start_date (Strava ISO 8601 string comparable
    # leksykograficznie). DDB Query sortuje po SK (ACTIVITY#{id}) co nie
    # jest chronologiczne — strava_id rośnie w czasie, ale leksykograficzne
    # comparison "10" < "9" psuje porządek dla user'ów z >9 activities.
    rows.sort(key=lambda r: str(r.get("start_date", "")), reverse=True)
    items = []
    for r in rows[:limit]:
        items.append(
            {
                "strava_id": _decimal_safe(r.get("strava_id")),
                "name": r.get("name"),
                "sport_type": r.get("sport_type"),
                "type": r.get("type"),
                "distance_m": _decimal_safe(r.get("distance_m")),
                "moving_time_s": _decimal_safe(r.get("moving_time_s")),
                "elapsed_time_s": _decimal_safe(r.get("elapsed_time_s")),
                "elevation_gain_m": _decimal_safe(r.get("elevation_gain_m")),
                "start_date": r.get("start_date"),
                "start_date_local": r.get("start_date_local"),
                "calories": _decimal_safe(r.get("calories")),
                "average_heartrate": _decimal_safe(r.get("average_heartrate")),
                "max_heartrate": _decimal_safe(r.get("max_heartrate")),
            }
        )

    logger.info(
        "activities_list",
        extra={
            "request_id": request_id,
            "handler": "activities_list",
            "user_id": user_id,
            "limit": limit,
            "returned": len(items),
        },
    )
    return _response(200, {"items": items})
