"""GET /api/strava/oauth/callback — Strava OAuth callback.

Strava redirektuje na ten endpoint po user authorize/cancel. Handler:
1. Validate query params (code + state, lub error).
2. Atomic DDB delete state row z `attribute_exists` guard → invalid_state
   gdy duplicate use lub czas pomiędzy mint i callback >10min.
3. Exchange code → tokens via Strava /oauth/token.
4. Persist tokens w SSM /bodysync/strava/{user_id}/tokens (SecureString).
5. Update SSM /bodysync/strava/athlete-to-user map (athlete_id → user_id)
   żeby webhook handler mógł zmapować incoming events na bodysync userów.
6. Redirect 302 do bodysync.pl/?strava=ok (lub error status).

Logger NIGDY nie zapisuje access_token / refresh_token / code w log fields
(test enforces).
"""

from __future__ import annotations

import time
from typing import Any

from handlers.strava_oauth_callback.service import (
    AthleteMapConflictError,
    StravaTokenExchangeError,
    exchange_code_for_tokens,
    frontend_redirect,
    tokens_ssm_path,
    update_athlete_map,
)
from shared.dynamo import delete_item_if_exists
from shared.logging import get_logger
from shared.ssm import get_param, put_param

logger = get_logger("strava_oauth_callback")

CLIENT_ID_PARAM = "/bodysync/strava/client_id"
CLIENT_SECRET_PARAM = "/bodysync/strava/client_secret"
ATHLETE_MAP_PARAM = "/bodysync/strava/athlete-to-user"


def _redirect(location: str) -> dict[str, Any]:
    return {
        "statusCode": 302,
        "headers": {"Location": location},
        "body": "",
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "local")
    qs: dict[str, str] = event.get("queryStringParameters") or {}

    # Strava sends `error=access_denied` gdy user kliknie Cancel.
    if qs.get("error"):
        logger.info(
            "user_denied",
            extra={"request_id": request_id, "reason": qs["error"][:50]},
        )
        return _redirect(frontend_redirect("denied"))

    code = qs.get("code")
    state = qs.get("state")
    if not code or not state:
        logger.warning("missing_params", extra={"request_id": request_id})
        return _redirect(frontend_redirect("missing_params"))

    # Atomic single-use state delete. ConditionalCheckFailed (state nie
    # istnieje lub został już usunięty) → invalid.
    state_row = delete_item_if_exists(f"STRAVA_OAUTH_STATE#{state}", "META")
    if state_row is None:
        logger.warning("invalid_state", extra={"request_id": request_id})
        return _redirect(frontend_redirect("invalid_state"))

    user_id = state_row.get("user_id")
    if not user_id:
        # Niemożliwe w normalnym flow (mint_state zawsze pisze user_id);
        # defensive guard jeśli ktoś ręcznie putitemnął row.
        logger.error("state_missing_user_id", extra={"request_id": request_id})
        return _redirect(frontend_redirect("invalid_state"))

    # DDB native TTL jest best-effort sweep (do 48h opóźnienia). Sprawdzamy
    # ręcznie żeby expired state nie został zaakceptowany w window.
    ttl = int(state_row.get("ttl") or 0)
    if ttl and ttl < int(time.time()):
        logger.warning(
            "expired_state",
            extra={"request_id": request_id, "user_id": user_id},
        )
        return _redirect(frontend_redirect("expired_state"))

    # Exchange code → tokens
    try:
        client_id = get_param(CLIENT_ID_PARAM, decrypt=False)
        client_secret = get_param(CLIENT_SECRET_PARAM)
    except Exception:
        logger.exception("ssm_config_error", extra={"request_id": request_id})
        return _redirect(frontend_redirect("config_error"))

    if client_id == "PLACEHOLDER" or client_secret == "PLACEHOLDER":
        logger.error("ssm_placeholder", extra={"request_id": request_id})
        return _redirect(frontend_redirect("config_error"))

    try:
        tokens = exchange_code_for_tokens(code, client_id, client_secret)
    except StravaTokenExchangeError as e:
        # NIE logujemy `code` ani Strava response body — fixed-vocabulary reason.
        logger.warning(
            "token_exchange_failed",
            extra={
                "request_id": request_id,
                "user_id": user_id,
                "reason": e.reason,
                "status_code": e.status_code,
            },
        )
        return _redirect(frontend_redirect("token_exchange_failed"))

    # Conflict check PRZED persist tokens — gdy athlete_id już jest mapped
    # do innego user_id (account takeover wektor przy >2 userach), nie chcemy
    # nadpisać per-user tokens path bo to wciąż per-user, ale zostawić mapę.
    # Owner ręcznie rozwiązuje konflikt w SSM `/bodysync/strava/athlete-to-user`.
    try:
        existing_map = get_param(ATHLETE_MAP_PARAM, decrypt=False)
    except Exception:
        existing_map = "{}"

    try:
        updated_map = update_athlete_map(existing_map, tokens.athlete_id, user_id)
    except AthleteMapConflictError as e:
        logger.warning(
            "athlete_already_mapped_to_other_user",
            extra={
                "request_id": request_id,
                "user_id": user_id,
                "athlete_id": e.athlete_id,
                "existing_user_id": e.existing_user_id,
            },
        )
        return _redirect(frontend_redirect("athlete_already_connected"))

    # Persist tokens (SecureString — encrypted at rest by KMS)
    try:
        put_param(
            tokens_ssm_path(user_id),
            tokens.model_dump_json(),
            secure=True,
            overwrite=True,
        )
    except Exception:
        logger.exception(
            "tokens_persist_error",
            extra={"request_id": request_id, "user_id": user_id},
        )
        return _redirect(frontend_redirect("persist_error"))

    # Update athlete-to-user map. Po conflict check'u więc bezpieczne nadpisanie.
    try:
        put_param(ATHLETE_MAP_PARAM, updated_map, secure=False, overwrite=True)
    except Exception:
        # Nie blokuj UX gdy map update fail — webhook handler ma fallback
        # (re-read SSM przy unknown athlete miss). Tokens już persistowane.
        logger.exception(
            "athlete_map_update_error",
            extra={"request_id": request_id, "user_id": user_id},
        )

    logger.info(
        "strava_oauth_callback_ok",
        extra={
            "request_id": request_id,
            "user_id": user_id,
            "handler": "strava_oauth_callback",
        },
    )
    return _redirect(frontend_redirect("ok"))
