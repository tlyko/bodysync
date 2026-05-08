"""Lambda handler dla DDB Streams trigger na EVENT#strava INSERT events.

Per-record try/catch — błąd w jednym record nie przerywa batch (Lambda
event source mapping iteruje przez batch i nie retry-uje pojedynczych
items, tylko cały batch — robimy własne handling).
"""

from __future__ import annotations

from typing import Any

from handlers.strava_fetcher.service import (
    FetcherSkipError,
    process_activity_record,
    unmarshal_record,
)
from shared.logging import get_logger

logger = get_logger("strava_fetcher")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    request_id = getattr(context, "aws_request_id", "local")
    records: list[dict[str, Any]] = event.get("Records") or []

    processed = 0
    skipped = 0
    errors = 0

    for record in records:
        if record.get("eventName") != "INSERT":
            skipped += 1
            continue

        try:
            data = unmarshal_record(record)
        except Exception:
            logger.exception(
                "unmarshal_failed",
                extra={"request_id": request_id, "handler": "strava_fetcher"},
            )
            errors += 1
            continue

        try:
            metrics = process_activity_record(data)
        except FetcherSkipError as e:
            logger.info(
                "record_skipped",
                extra={
                    "request_id": request_id,
                    "handler": "strava_fetcher",
                    "reason": e.reason,
                },
            )
            skipped += 1
            continue
        except Exception:
            logger.exception(
                "record_processing_error",
                extra={
                    "request_id": request_id,
                    "handler": "strava_fetcher",
                    "user_id": data.get("user_id"),
                    "object_id": data.get("object_id"),
                },
            )
            errors += 1
            continue

        if metrics:
            logger.info(
                "strava_fetcher_processed",
                extra={
                    "request_id": request_id,
                    "handler": "strava_fetcher",
                    **metrics,
                },
            )
            processed += 1

    logger.info(
        "strava_fetcher_batch",
        extra={
            "request_id": request_id,
            "handler": "strava_fetcher",
            "processed": processed,
            "skipped": skipped,
            "errors": errors,
        },
    )
    # DDB Streams iterators expect zwykłe return (no batch failure semantics
    # used here — per-record handling above).
    return {"processed": processed, "skipped": skipped, "errors": errors}
