"""AWS Lambda entrypoint dla `POST /api/advisor/chat` + `GET /api/advisor/chat/history`.

POST flow per ADR-007 (Sprint 6.1 PR1) — multi-turn chat z RAG retrieval.
GET history flow (Sprint 10 A1) — frontend hydrate na mount, refresh page
nie traci kontekstu rozmowy. Wspólny handler bo te same DDB CHAT# pattern
+ same JWT auth — separate Lambda by mnożyć cold start ostentacyjnie.

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

from handlers.advisor_chat import rag, service
from handlers.advisor_chat._history_handler import (
    handle_delete_history as _handle_delete_history,
)
from handlers.advisor_chat._history_handler import handle_get_history as _handle_get_history
from handlers.advisor_chat.schemas import (
    ChatRequest,
    ChatResponse,
    UsedRecipe,
)
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
    """Lambda entrypoint dla `POST /api/advisor/chat` + `GET /api/advisor/chat/history`.

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

    # ── 1.5 Route dispatch — GET/DELETE history vs POST chat ──────────────
    method = (event.get("requestContext") or {}).get("http", {}).get("method", "")
    if method == "GET":
        return _handle_get_history(event, user_id, request_id)
    if method == "DELETE":
        return _handle_delete_history(event, user_id, request_id)
    # else: POST flow (default; explicit method check w istniejącej logice).

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
        # NOTE: 30/day cap is best-effort; concurrent requests may briefly
        # exceed by N. Cost-guard CloudWatch alarm at 1.5M output tokens/day
        # backstops absolute cost. ADR-007 spec line 867 explicit accept for
        # 2-user MVP (no atomic counter — over-engineering).
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
        # Pass `history` snapshot — pierwsza próba w `append_message` używa go
        # bez zduplikowanego DDB Query; collision-retry re-readuje fresh.
        user_turn_idx = service.append_message(
            user_id,
            today,
            "user",
            request.message,
            history=history,
        )

        # ── 6. Build context + messages ────────────────────────────────────
        today_state = service.build_today_state(user_id, today)

        # ── 6.5 RAG retrieval (per ADR-007 D6 — top-K=5 cosine recipes) ────
        # Topical gate: skip RAG gdy user pyta NIE o jedzenie (waga, trening,
        # regeneracja). Oszczędza embedding + S3 + FAISS cost gdy recipe
        # cards by były off-topic. Owner UX feedback: nie pokazuj przepisów
        # przy pytaniu o wagę lub trening.
        #
        # Graceful degradation: każda RAG porażka (S3 missing, OpenAI down,
        # FAISS broken) → `retrieved=None`, chat kontynuuje bez recipes.
        # NIE leakujemy SDK exception body do logów (per ADR-007 OPEN-4).
        retrieved: list[UsedRecipe] | None = None
        food_related = service.is_food_related(request.message)
        if not food_related:
            logger.info(
                "rag_skipped_non_food_query",
                extra={"request_id": request_id, "user_id": user_id},
            )
        else:
            try:
                retrieved = rag.retrieve(request.message, k=5)
            except rag.RAGUnavailableError as exc:
                logger.warning(
                    "rag_unavailable",
                    extra={
                        "request_id": request_id,
                        "user_id": user_id,
                        "reason": exc.reason,
                        "status_code": exc.status_code,
                    },
                )
            except Exception as exc:  # noqa: BLE001 — RAG nie może crashować chatu
                # Catch-all jako defense-in-depth. `exc_type` only (klasa), bez
                # `str(exc)` — third-party SDK może echo'ować prompt w `__str__`.
                logger.error(
                    "rag_unexpected_error",
                    extra={
                        "request_id": request_id,
                        "user_id": user_id,
                        "exc_type": type(exc).__name__,
                    },
                )

        # ── 6.6 Training plan injection (Sprint 5 PR #4) ───────────────────
        # Best-effort load z DDB (PK=USER#{id} SK=PLAN#current — populated
        # przez handlers.plan przy każdym successful fetch z Google Sheets).
        # Brak planu (owner nie skonfigurował SSM lub frontend nigdy nie
        # wywołał /api/plan) → None → block pominięty w prompt.
        training_plan = None
        try:
            training_plan = service.load_training_plan(user_id)
        except Exception as exc:  # noqa: BLE001 — DDB nie crashuje chatu
            logger.warning(
                "training_plan_load_failed",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "exc_type": type(exc).__name__,
                },
            )

        # ── 6.7 Recent activities injection ────────────────────────────────
        # 7-day window Strava activities z DDB (ACTIVITY#{strava_id} rows
        # zapisane przez strava_fetcher). Bez tego LLM widzi tylko zsumowane
        # step_count + kcal_active z HAE — brak konkretnego sport_type/dystans/
        # tempa/HR per trening. Best-effort: błąd DDB nie crashuje chatu.
        recent_activities: list = []
        try:
            recent_activities = service.load_recent_activities(user_id, today=today)
        except Exception as exc:  # noqa: BLE001 — DDB nie crashuje chatu
            logger.warning(
                "recent_activities_load_failed",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "exc_type": type(exc).__name__,
                },
            )

        # `history` to snapshot SPRZED appendu user turn — `build_chat_messages`
        # samo wrapuje `request.message` w `<user_message>` block, więc nie
        # duplikujemy (gdybyśmy wzięli post-append history, mielibyśmy bieżącą
        # wiadomość zarówno w `<conversation_history>` jak i `<user_message>`).
        messages = service.build_chat_messages(
            history,
            today_state,
            request.message,
            retrieved_recipes=retrieved,
            training_plan=training_plan,
            recent_activities=recent_activities,
        )

        # ── 7. Anthropic call ──────────────────────────────────────────────
        try:
            content, tokens = service.call_chat(SYSTEM_PROMPT, messages)
        except AdvisorUnavailableError:
            logger.warning(
                "advisor_api_key_missing",
                extra={"request_id": request_id, "user_id": user_id},
            )
            return _response(503, {"error": "advisor_unavailable"})
        except AdvisorBackendError as exc:
            # logger.error (NIE .exception) — `exc_info` byłby formatException'em
            # przez JsonFormatter i mógłby echo'ować Anthropic SDK body
            # (np. 4xx z `prompt too long: <snippet>`). Logujemy tylko
            # category code + status — per ADR-007 OPEN-4.
            logger.error(
                "advisor_backend_error",
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "reason": exc.reason,
                    "status_code": exc.status_code,
                },
            )
            return _response(503, {"error": "advisor_backend_error"})

        # ── 8. Append assistant turn ───────────────────────────────────────
        # Pragmatic: nie budujemy `history_after_user` snapshotu — re-Query
        # raz po Anthropic call (~kilkaset ms) jest tańsze niż utrzymanie
        # spójnego mutowanego snapshota. Race window: minimal (drugi turn
        # idx liczony świeżo z DDB).
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
            used_recipes=retrieved or [],
            turn_idx=assistant_turn_idx,
            tokens_used=tokens,
            generated_at=datetime.now(UTC).isoformat(),
        )

        retrieved_slugs = [r.slug for r in retrieved] if retrieved else []
        logger.info(
            "chat_turn_complete",
            extra={
                "request_id": request_id,
                "user_id": user_id,
                "user_turn_idx": user_turn_idx,
                "assistant_turn_idx": assistant_turn_idx,
                "history_size": len(history),
                # Match `anthropic_call` log shape (allowlist + cost-guard
                # CloudWatch metric filter convention).
                "input_tokens": tokens.input_tokens,
                "output_tokens": tokens.output_tokens,
                # Sprint 6.2 RAG observability (per ADR-007 OPEN-4):
                # slugi (NIE content) + count, dla CloudWatch debug.
                "retrieved_slugs": retrieved_slugs,
                "retrieved_count": len(retrieved_slugs),
                # Sprint 5 PR #4 — plan injection observability.
                "training_plan_present": training_plan is not None,
                "training_plan_rows": (len(training_plan.rows) if training_plan else 0),
            },
        )

        return _response(200, response.model_dump())

    except Exception as exc:
        # Catch-all — logujemy `exc_type` (klasa) zamiast traceback/`str(exc)`.
        # Powód: nieznane wyjątki mogą mieć `__str__` zawierający payload
        # (np. third-party SDK echo'ujący request). Per ADR-007 OPEN-4
        # "no content logging" — debug przez X-Ray / lokalne replay.
        logger.error(
            "chat_internal_error",
            extra={
                "request_id": request_id,
                "user_id": user_id,
                "exc_type": type(exc).__name__,
            },
        )
        return _response(500, {"error": "internal_error"})
