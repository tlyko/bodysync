"""Health Auto Export ingest service.

Flow:
1. Identyfikacja usera po Bearer secret (`hmac.compare_digest` per kandydat,
   constant-time loop bez early-return — privacy + scaling pattern).
2. Per metric w payload: lookup w `METRIC_HANDLERS` registry → ingest fn
   parsuje raw dict, mapuje do SK i atrybutów, pisze do DDB.
3. Unknown metric name → log warn + skip (forward-compat — nowy iOS metric
   nie blokuje całego batcha).

Sprint 3 PR A obsługuje 2 metryki: HRV (multi-point per dzień, idempotent
po `recorded_at`) i step_count (single-point per dzień, last-writer-wins).
Pozostałe (heart_rate, sleep, kcal, weight, body_fat, dietary) dochodzą
w PR B.
"""

from __future__ import annotations

import hmac
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from handlers.health_webhook.schemas import (
    HAEHeartRatePoint,
    HAEPayload,
    HAEScalarPoint,
    HAESleepPoint,
)
from shared.dynamo import put_item, put_item_idempotent
from shared.ssm import SecretMisconfiguredError, load_secure_secret

logger = logging.getLogger(__name__)

# Daty z HAE są w timezone telefonu (zwykle Europe/Warsaw). SK używa
# YYYY-MM-DD w czasie lokalnym, żeby kroki sprzed 2:00 UTC trafiły do
# poprzedniego dnia (po polsku — tego samego dnia życia).
LOCAL_TZ = ZoneInfo("Europe/Warsaw")

# Per user — SSM SecureString z webhook secretem. Hardcoded żeby uniknąć
# parametryzacji per Lambda env (DRY: secret list jest stała dla 2 userów).
USER_SECRET_PARAMS: dict[str, str] = {
    "tomek": "/bodysync/health-auto-export/webhook_secret_tomek",
    "partner": "/bodysync/health-auto-export/webhook_secret_partner",
}
SECRET_MIN_LENGTH = 32


class AuthFailedError(Exception):
    """Bearer header missing/malformed/no-match — handler zwraca 401."""


@dataclass
class IngestResult:
    received: int = 0
    stored: int = 0
    skipped_unknown: int = 0


def resolve_user_from_bearer(bearer: str) -> str:
    """Constant-time match Bearer'a z SSM secrets per user.

    Zawsze sprawdza wszystkich kandydatów (bez early-return) — pattern dla
    timing-leak resistance gdy lista userów rośnie. Dla 2 userów pomijalne,
    ale wzorzec spójny.

    Skip secrets ktorych SSM zwraca jako PLACEHOLDER lub <32 chars
    (`load_secure_secret` rzuca → łapiemy i traktujemy jak miss).
    """
    matched: str | None = None
    for user_id, ssm_name in USER_SECRET_PARAMS.items():
        try:
            secret = load_secure_secret(ssm_name, min_length=SECRET_MIN_LENGTH)
        except SecretMisconfiguredError:
            # Secret nie ustawiony przez ownera — traktujemy jak miss.
            # Bez tego placeholder "PLACEHOLDER" pasowałby do każdego "PLACEHOLDER" wysłanego.
            continue
        if hmac.compare_digest(bearer, secret) and matched is None:
            matched = user_id
    if matched is None:
        raise AuthFailedError("no matching webhook secret")
    return matched


# ─── Per-metric ingest functions ──────────────────────────────────────────


def _local_date_iso(dt: datetime) -> str:
    return dt.astimezone(LOCAL_TZ).date().isoformat()


def _common_attrs(point: HAEScalarPoint, ingested_at: datetime) -> dict[str, Any]:
    return {
        "source": "apple-health",
        "device": point.source,
        "recorded_at": point.date.isoformat(),
        "ingested_at": ingested_at.isoformat(),
    }


def _ingest_hrv(user_id: str, raw: dict[str, Any], ingested_at: datetime) -> bool:
    """HRV: multi-point per dzień (HAE wysyła ~10-24 readings/dzień).

    SK z timestampem dla idempotency — replay tego samego point = NOOP.
    Atrybut `value_ms` w czytelnej jednostce.
    """
    point = HAEScalarPoint.model_validate(raw)
    sk = f"BIOMETRY#{_local_date_iso(point.date)}#hrv#{point.date.isoformat()}"
    attrs = {"value_ms": point.qty, **_common_attrs(point, ingested_at)}
    return put_item_idempotent(f"USER#{user_id}", sk, attrs)


def _ingest_steps(user_id: str, raw: dict[str, Any], ingested_at: datetime) -> bool:
    """Kroki: single-point per dzień (cumulative). HAE wysyła "do tej pory"
    z dzisiaj — last-writer-wins. SK bez timestamp.
    """
    point = HAEScalarPoint.model_validate(raw)
    sk = f"BIOMETRY#{_local_date_iso(point.date)}#steps"
    attrs = {"count": int(point.qty), **_common_attrs(point, ingested_at)}
    put_item(f"USER#{user_id}", sk, attrs)
    return True


def _make_scalar_upsert(
    short_name: str, value_key: str
) -> Callable[[str, dict[str, Any], datetime], bool]:
    """Factory dla mapperów single-point upsert: kcal, weight, body fat,
    dietary, resting HR. SK bez timestamp = last-writer-wins.

    `short_name` → fragment SK (e.g. 'weight', 'kcal_active').
    `value_key` → nazwa attrs do zapisania value (e.g. 'kg', 'kcal').
    """

    def _ingest(user_id: str, raw: dict[str, Any], ingested_at: datetime) -> bool:
        point = HAEScalarPoint.model_validate(raw)
        sk = f"BIOMETRY#{_local_date_iso(point.date)}#{short_name}"
        attrs = {value_key: point.qty, **_common_attrs(point, ingested_at)}
        put_item(f"USER#{user_id}", sk, attrs)
        return True

    return _ingest


def _ingest_heart_rate(user_id: str, raw: dict[str, Any], ingested_at: datetime) -> bool:
    """`heart_rate` per okno czasowe — Min/Avg/Max. Multi-point z timestampem,
    idempotent. Storage: 3 wartości per row, advisor czyta avg dziennie.
    """
    point = HAEHeartRatePoint.model_validate(raw)
    sk = f"BIOMETRY#{_local_date_iso(point.date)}#hr#{point.date.isoformat()}"
    attrs = {
        "min_bpm": point.Min,
        "avg_bpm": point.Avg,
        "max_bpm": point.Max,
        "source": "apple-health",
        "device": point.source,
        "recorded_at": point.date.isoformat(),
        "ingested_at": ingested_at.isoformat(),
    }
    return put_item_idempotent(f"USER#{user_id}", sk, attrs)


def _ingest_sleep(user_id: str, raw: dict[str, Any], ingested_at: datetime) -> bool:
    """`sleep_analysis` summary per noc. Single-point per dzień, upsert.

    HAE wysyła sumaryczne wartości (inBed, asleep, core, rem, deep, awake)
    po przebudzeniu. Replay = overwrite (nowa noc nadpisze, ale w praktyce
    HAE wysyła raz, po wstaniu).
    """
    point = HAESleepPoint.model_validate(raw)
    sk = f"BIOMETRY#{_local_date_iso(point.date)}#sleep"
    attrs: dict[str, Any] = {
        "source": "apple-health",
        "device": point.source,
        "recorded_at": point.date.isoformat(),
        "ingested_at": ingested_at.isoformat(),
    }
    # Pomijamy None'y żeby nie zaśmiecać DDB.
    for field in ("inBed", "asleep", "core", "rem", "deep", "awake"):
        value = getattr(point, field)
        if value is not None:
            attrs[field] = value
    for field in ("inBedStart", "inBedEnd", "sleepStart", "sleepEnd"):
        value = getattr(point, field)
        if value is not None:
            attrs[field] = value.isoformat()
    put_item(f"USER#{user_id}", sk, attrs)
    return True


METRIC_HANDLERS: dict[str, Callable[[str, dict[str, Any], datetime], bool]] = {
    # multi-point z idempotency
    "heart_rate_variability": _ingest_hrv,
    "heart_rate": _ingest_heart_rate,
    # single-point upsert per dzień
    "step_count": _ingest_steps,
    "sleep_analysis": _ingest_sleep,
    "resting_heart_rate": _make_scalar_upsert("resting_hr", "bpm"),
    "active_energy": _make_scalar_upsert("kcal_active", "kcal"),
    "basal_energy_burned": _make_scalar_upsert("kcal_basal", "kcal"),
    "weight_body_mass": _make_scalar_upsert("weight", "kg"),
    "body_fat_percentage": _make_scalar_upsert("body_fat", "pct"),
    "dietary_energy": _make_scalar_upsert("kcal_in", "kcal"),
    "protein": _make_scalar_upsert("protein", "g"),
    "total_fat": _make_scalar_upsert("fat", "g"),
    "carbohydrates": _make_scalar_upsert("carbs", "g"),
}


def ingest(user_id: str, payload: HAEPayload, *, ingested_at: datetime) -> IngestResult:
    """Przetwarza payload metric-by-metric. Zwraca counters dla response body."""
    result = IngestResult()

    for metric in payload.data.metrics:
        handler = METRIC_HANDLERS.get(metric.name)
        if handler is None:
            logger.warning(
                "unknown_hae_metric", extra={"metric_name": metric.name, "user_id": user_id}
            )
            result.skipped_unknown += len(metric.data)
            continue

        for raw_point in metric.data:
            result.received += 1
            try:
                stored = handler(user_id, raw_point, ingested_at)
            except Exception:
                # Pojedynczy bad point nie wywala batcha — log + continue.
                # Pełny payload retried przez HAE byłby gorszy (storm
                # tych samych błędów).
                logger.exception(
                    "hae_point_ingest_failed",
                    extra={"metric_name": metric.name, "user_id": user_id},
                )
                continue
            if stored:
                result.stored += 1

    if payload.data.workouts:
        # MVP: Strava jest sole source dla activities (CLAUDE.md domain).
        # Logujemy tylko żeby było widać w CloudWatch ile się "marnuje".
        logger.info(
            "hae_workouts_skipped",
            extra={"count": len(payload.data.workouts), "user_id": user_id},
        )

    return result
