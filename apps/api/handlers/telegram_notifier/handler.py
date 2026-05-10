"""AWS Lambda — SNS subscriber dla `bodysync-cost-guard` topic.

Forwarduje CloudWatch alarm payload (Anthropic cost-guard threshold breach
+ recovery) na Telegram bota. Zastępuje email subscription (Gmail auto-
unsub'uje SNS notifications, więc owner nigdy nie dostawał alertów).

Best-effort — jeśli Telegram API nie odpowiada (4xx/5xx/timeout) handler
loguje warning i zwraca success. SNS retry nie pomoże:
1. CloudWatch alarm = singular event (ALARM/OK transition) — duplikat
   zaszkodzi bardziej niż brak.
2. Jeśli Telegram down to alarm i tak siedzi w CloudWatch — owner widzi
   sumarycznie po fakcie.
3. Lambda exception → SNS retries → DLQ → alerting loop bez końca.

Stdlib only (`urllib.request`) — no external deps, smaller zip, faster
cold start.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from shared.logging import get_logger
from shared.ssm import SecretMisconfiguredError, get_param, load_secure_secret

logger = get_logger("telegram_notifier")

TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_TIMEOUT_S = 5  # match Lambda 5s timeout budget
BOT_TOKEN_PARAM = "/bodysync/telegram/bot_token"
CHAT_ID_PARAM = "/bodysync/telegram/chat_id"

# Telegram bot tokens mają format `<bot_id>:<auth_string>` długości ~46 chars.
# Min 32 to defense-in-depth przeciw PLACEHOLDER / pustemu stringowi.
BOT_TOKEN_MIN_LEN = 32

_STATE_ICON = {
    "ALARM": "🚨",
    "OK": "✅",
    "INSUFFICIENT_DATA": "⚠️",
}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """SNS event → Telegram message.

    Event format (CloudWatch alarm via SNS):
      {
        "Records": [{
          "Sns": {
            "Message": "<JSON string z alarm payload>"
          }
        }]
      }

    Alarm payload:
      {
        "AlarmName": "bodysync-anthropic-daily-cost-high",
        "NewStateValue": "ALARM" | "OK" | "INSUFFICIENT_DATA",
        "NewStateReason": "Threshold Crossed: ...",
        "StateChangeTime": "2026-05-09T12:00:00.000+0000",
        ...
      }
    """
    request_id = getattr(context, "aws_request_id", "local")

    try:
        records = event.get("Records") or []
        if not records:
            logger.warning("sns_event_empty", extra={"request_id": request_id})
            return {"ok": False, "reason": "no_records"}
        sns_message_str = records[0]["Sns"]["Message"]
        alarm = json.loads(sns_message_str)
    except (KeyError, TypeError, json.JSONDecodeError) as e:
        logger.warning(
            "sns_event_malformed",
            extra={"request_id": request_id, "reason": type(e).__name__},
        )
        return {"ok": False, "reason": "malformed_event"}

    text = _format_alarm_message(alarm)
    sent = _send_to_telegram(text, request_id=request_id)
    return {"ok": sent}


def _format_alarm_message(alarm: dict[str, Any]) -> str:
    """Render alarm jako Telegram HTML.

    HTML escape obowiązkowy bo `AlarmName`/`NewStateReason` mogą zawierać
    `<`/`>`/`&` (np. "Threshold > 1500000.0" w reason).
    """
    state = alarm.get("NewStateValue", "?")
    name = alarm.get("AlarmName", "?")
    reason = alarm.get("NewStateReason", "?")
    time = alarm.get("StateChangeTime", "?")
    icon = _STATE_ICON.get(state, "ℹ️")

    return (
        f"{icon} <b>Cost guard {_escape_html(state)}</b>\n"
        f"<b>Alarm:</b> {_escape_html(name)}\n"
        f"<b>Powód:</b> {_escape_html(reason)}\n"
        f"<b>Czas:</b> {_escape_html(time)}"
    )


def _escape_html(text: str) -> str:
    # Telegram HTML mode: escape only `&`, `<`, `>` (per Bot API docs).
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _send_to_telegram(text: str, *, request_id: str) -> bool:
    try:
        bot_token = load_secure_secret(BOT_TOKEN_PARAM, min_length=BOT_TOKEN_MIN_LEN)
        chat_id = get_param(CHAT_ID_PARAM, decrypt=False)
    except SecretMisconfiguredError:
        logger.warning(
            "telegram_secret_missing",
            extra={"request_id": request_id, "reason": "bot_token_placeholder"},
        )
        return False

    if chat_id == "PLACEHOLDER" or not chat_id:
        logger.warning(
            "telegram_secret_missing",
            extra={"request_id": request_id, "reason": "chat_id_placeholder"},
        )
        return False

    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TELEGRAM_TIMEOUT_S) as resp:
            # urllib rzuca HTTPError dla >=400, więc tutaj zawsze 2xx/3xx.
            logger.info(
                "telegram_sent",
                extra={"request_id": request_id, "status_code": resp.status},
            )
        return True
    except urllib.error.HTTPError as e:
        logger.warning(
            "telegram_send_failed",
            extra={
                "request_id": request_id,
                "status_code": e.code,
                "reason": "http_error",
            },
        )
        return False
    except (urllib.error.URLError, TimeoutError) as e:
        logger.warning(
            "telegram_send_failed",
            extra={"request_id": request_id, "reason": type(e).__name__},
        )
        return False
