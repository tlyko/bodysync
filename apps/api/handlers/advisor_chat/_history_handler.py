"""GET /api/advisor/chat/history dispatch (Sprint 10 A1).

Wydzielone do osobnego pliku żeby `handler.py` (~340 LOC) nie urósł
ponad próg czytelności. Importowane wprost z `handler.py`.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from handlers.advisor_chat import service
from handlers.advisor_chat.schemas import ChatHistoryResponse
from shared.logging import get_logger

logger = get_logger("advisor_chat_history")

WARSAW_TZ = ZoneInfo("Europe/Warsaw")


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def _parse_date_param(qs: dict[str, str]) -> date | None:
    """Parse `?date=YYYY-MM-DD` query param. Returns None gdy nie podany.

    Invalid format → None (handler użyje today). Konserwatywne — nie
    rzucamy 400 dla śmieciowego query param, po prostu fallback na today.
    """
    raw = qs.get("date")
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def handle_get_history(event: dict[str, Any], user_id: str, request_id: str) -> dict[str, Any]:
    """Read chat history for given date (default today w Europe/Warsaw).

    NIE liczy się do `DAILY_USER_TURN_LIMIT` — to read-only history fetch,
    nie generuje LLM calli. Brak rate limit; DDB Query 1× per request.

    Empty history (brak rozmów) → 200 z `messages: []` (NIE 404).
    """
    qs: dict[str, str] = event.get("queryStringParameters") or {}
    parsed = _parse_date_param(qs)
    target_date = parsed or datetime.now(UTC).astimezone(WARSAW_TZ).date()

    try:
        messages = service.read_history(user_id, target_date)
    except Exception:
        logger.exception(
            "history_read_failed",
            extra={"request_id": request_id, "user_id": user_id},
        )
        return _response(500, {"error": "internal_error"})

    response = ChatHistoryResponse(messages=messages, date=target_date.isoformat())
    logger.info(
        "history_get",
        extra={
            "request_id": request_id,
            "user_id": user_id,
            "history_size": len(messages),
        },
    )
    return _response(200, response.model_dump())
