"""Structured logger. Format: JSON line per event z request_id + user_id.

NEVER log raw payloads — webhooks mogą nieść PII (email, body_mass, HRV).
Zamiast: log type + count + fingerprint, nie zawartość.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in (
            "request_id",
            "user_id",
            "handler",
            "duration_ms",
            "reason",
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "model",
            # advisor_chat handler observability (chat_turn_complete /
            # rate_limit_exceeded / chat_request_received).
            "user_turn_idx",
            "assistant_turn_idx",
            "history_size",
            "message_length",
            "limit",
            "used",
            # advisor_chat profile-targets fallback diagnostics
            # (`profile_targets_default` log w `_load_profile_targets`).
            "has_kcal_target",
            "has_protein_target",
            # advisor_chat error diagnostics — fixed-vocabulary code
            # (NIE Anthropic SDK exception message) + HTTP status_code +
            # exception class name (catch-all 500 path).
            "status_code",
            "exc_type",
            # advisor_chat RAG observability (Sprint 6.2 PR2 per ADR-007
            # OPEN-4) — slugi (NIE content) + count w `chat_turn_complete`
            # plus `rag_retrieve_complete` w rag.py: query_length, top_score,
            # results_count, slugs (per-call detailed metrics).
            "retrieved_slugs",
            "retrieved_count",
            "query_length",
            "top_score",
            "results_count",
            "slugs",
            # Sprint 4 Strava webhook observability — identity check fields,
            # idempotency duplicate flag. NIGDY nie loggujemy full payload
            # (PII: athlete name + activity coordinates) — tylko enums + ids.
            "object_id",
            "object_type",
            "aspect_type",
            "subscription_id",
            "owner_id",
            "received_sub",
            "duplicate",
            # waitlist (Sprint 12 PR1 — landing signup). Hash fingerprints
            # NIE plain email/IP (PII) — owner widzi same-user resubmit
            # bez deanonymizacji w logach.
            "email_hash",
            "ip_hash",
            "has_interest",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
    logger.propagate = False
    return logger
