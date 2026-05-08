"""AWS Lambda entrypoint dla `POST /api/advisor/chat` (Sprint 6.1 PR1 per ADR-007).

Flow:
1. JWT cookie verify (`bodysync_session`) → `user_id`.
2. Pydantic parse `ChatRequest` z body (message 1-2000 chars).
3. Read history once (DDB Query `CHAT#{today}#`).
4. Rate limit: max 30 user turns/dzień (ADR-007 D6).
5. Append user turn FIRST (UX continuity gdy Anthropic fail po appendzie).
6. Build today_state + chat messages (single user message z `<conversation_history>`
   + `<today_context>` + `<user_message>` blocks; system prompt cached).
7. Call Anthropic Haiku via `service.call_chat`.
8. Append assistant turn z `tokens_used`.
9. Zwróć `ChatResponse(used_recipes=[], ...)`.

Status codes:
- 200 OK + JSON `ChatResponse`
- 400 Bad Request — invalid JSON / Pydantic ValidationError
- 401 Unauthorized — brak / niepoprawny JWT
- 429 Too Many Requests — daily quota exceeded (>30 user turns)
- 503 Service Unavailable — Anthropic key missing (PLACEHOLDER) lub backend error
- 500 Internal Server Error — catch-all (logged with traceback)

NO content logging (ADR-007 OPEN-4) — log tylko `message_length`, turn indices,
token counts. PII / user content nigdy do CloudWatch.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from handlers.advisor_chat import service
from handlers.advisor_chat.schemas import ChatRequest, ChatResponse
from handlers.advisor_chat.service import (
    AdvisorBackendError,
    AdvisorUnavailableError,
)
from shared.auth import AuthError, verify_jwt
from shared.logging import get_logger

logger = get_logger("advisor_chat")

COOKIE_NAME = "bodysync_session"
WARSAW_TZ = ZoneInfo("Europe/Warsaw")

# Daily user-turn quota per ADR-007 D6 — chroni przed runaway koszty Anthropic.
DAILY_USER_TURN_LIMIT = 30

# System prompt loaded once per cold start (file read w service.py module init).
# Reuse zamiast re-read — match pattern z PR #50 (file read once, content reused
# per invocation). Path resolution dzieje się w `service._SYSTEM_PROMPT_PATH`
# (relative do tego module dir via `Path(__file__).parent`).
SYSTEM_PROMPT = service._SYSTEM_PROMPT


def _response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    """Build API GW HTTP API v2 response envelope."""
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def _extract_session_cookie(event: dict[str, Any]) -> str | None:
    """Mirror api_read._extract_session_cookie — API GW HTTP API v2 daje
    `cookies: list[str]` w event payload, fallback na `Cookie` header."""
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


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entrypoint dla `POST /api/advisor/chat`.

    Handler nie loguje user content (ADR-007 OPEN-4). Każdy structured log
    ma `request_id` + `user_id` (gdy znany).
    """
    request_id = getattr(context, "aws_request_id", "local")

    # ── 1. JWT verify ──────────────────────────────────────────────────────
    token = _extract_session_cookie(event)
    if not token:
        logger.info("missing_session", extra={"request_id": request_id})
        return _response(401, {"error": "auth_required"})
    try:
        payload = verify_jwt(token)
    except AuthError:
        logger.info("invalid_session", extra={"request_id": request_id})
        return _response(401, {"error": "auth_required"})
    user_id = payload.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        logger.warning("session_no_user_id", extra={"request_id": request_id})
        return _response(401, {"error": "auth_required"})

    # ── 2. Parse body ──────────────────────────────────────────────────────
    raw_body = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64

        raw_body = base64.b64decode(raw_body).decode("utf-8")
    if not raw_body.strip():
        raw_body = "{}"
    try:
        body_dict = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning("invalid_json", extra={"request_id": request_id, "user_id": user_id})
        return _response(400, {"error": "invalid_request", "details": "invalid json body"})

    try:
        request = ChatRequest.model_validate(body_dict)
    except ValidationError as exc:
        # Sanityzacja per CLAUDE.md "bez payloadu w logach" — `loc`+`type` only.
        sanitized = [{"loc": err["loc"], "type": err["type"]} for err in exc.errors()]
        logger.warning("invalid_payload", extra={"request_id": request_id, "user_id": user_id})
        return _response(400, {"error": "invalid_request", "details": sanitized})

    logger.info(
        "chat_request_received",
        extra={
            "request_id": request_id,
            "user_id": user_id,
            "message_length": len(request.message),
        },
    )

    today = datetime.now(WARSAW_TZ).date()

    # ── 3-5. Read history + rate limit + append user turn ──────────────────
    try:
        history = service.read_history(user_id, today)
        user_count = sum(1 for m in history if m.role == "user")
        if user_count >= DAILY_USER_TURN_LIMIT:
            logger.warning(
                "rate_limit_exceeded",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "limit": DAILY_USER_TURN_LIMIT,
                    "used": user_count,
                },
            )
            return _response(
                429,
                {
                    "error": "daily_quota",
                    "limit": DAILY_USER_TURN_LIMIT,
                    "used": user_count,
                },
            )

        # Append user turn FIRST — UX continuity: gdy Anthropic fail po appendzie,
        # user widzi swoją wiadomość w UI i może retry (per ADR-007 + spec line 1036).
        user_turn_idx = service.append_message(user_id, today, "user", request.message)

        # ── 6. Build context + messages ────────────────────────────────────
        today_state = service.build_today_state(user_id, today)
        # `history` to snapshot SPRZED appendu user turn — `build_chat_messages`
        # samo wrapuje `request.message` w `<user_message>` block, więc nie
        # duplikujemy (gdybyśmy wzięli post-append history, mielibyśmy bieżącą
        # wiadomość zarówno w `<conversation_history>` jak i `<user_message>`).
        messages = service.build_chat_messages(history, today_state, request.message)

        # ── 7. Anthropic call ──────────────────────────────────────────────
        try:
            content, tokens = service.call_chat(SYSTEM_PROMPT, messages)
        except AdvisorUnavailableError:
            logger.warning(
                "advisor_api_key_missing",
                extra={"request_id": request_id, "user_id": user_id},
            )
            return _response(503, {"error": "advisor_unavailable"})
        except AdvisorBackendError:
            logger.exception(
                "advisor_backend_error",
                extra={"request_id": request_id, "user_id": user_id},
            )
            return _response(503, {"error": "advisor_backend_error"})

        # ── 8. Append assistant turn ───────────────────────────────────────
        assistant_turn_idx = service.append_message(
            user_id,
            today,
            "assistant",
            content,
            tokens_used=tokens.model_dump(),
        )

        # ── 9. Build response ──────────────────────────────────────────────
        response = ChatResponse(
            role="assistant",
            content=content,
            used_recipes=[],  # PR1 placeholder; PR2 fills via RAG.
            turn_idx=assistant_turn_idx,
            tokens_used=tokens,
            generated_at=datetime.now(UTC).isoformat(),
        )

        logger.info(
            "chat_turn_complete",
            extra={
                "request_id": request_id,
                "user_id": user_id,
                "user_turn_idx": user_turn_idx,
                "assistant_turn_idx": assistant_turn_idx,
                "history_size": len(history),
                "tokens_input": tokens.input_tokens,
                "tokens_output": tokens.output_tokens,
            },
        )

        return _response(200, response.model_dump())

    except Exception:
        # Catch-all — log full traceback, return generic 500 (no internal leak).
        logger.exception(
            "chat_internal_error",
            extra={"request_id": request_id, "user_id": user_id},
        )
        return _response(500, {"error": "internal_error"})
