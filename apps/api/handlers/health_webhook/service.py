"""Health Auto Export ingest service.

Flow:
1. Identyfikacja usera po Bearer secret (`hmac.compare_digest` per kandydat,
   constant-time loop bez early-return — privacy + scaling pattern).
2. Per metric w payload: lookup w `METRIC_HANDLERS` registry → ingest fn
   parsuje raw dict, mapuje do SK i atrybutów, pisze do DDB.
3. Unknown metric name → log warn + skip (forward-compat — nowy iOS metric
   nie blokuje całego batcha).

Cumulative vs snapshot model (Sprint 3.5):
- **Cumulative metrics** (HAE iOS `Aggregation: Hour` wysyła N punktów / dzień):
  `step_count`, `active_energy`, `basal_energy_burned`, `dietary_energy`,
  `protein`, `total_fat`, `carbohydrates` + `heart_rate` / `heart_rate_variability`.
  SK ma `#{metric}#{point.date.isoformat()}` żeby każdy hourly bucket był
  osobnym item — sum read-time przez `sum_metric_today`. Replay = idempotent.
- **Snapshot metrics** (HAE wysyła sumaryczny punkt po pomiarze):
  `weight_body_mass`, `body_fat_percentage`, `resting_heart_rate`,
  `sleep_analysis`. SK bez timestamp = last-writer-wins.
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
    "weronika": "/bodysync/health-auto-export/webhook_secret_weronika",
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


# ─── Units handling (kJ→kcal, validation) ─────────────────────────────────

# Współczynnik konwersji energii zgodny z HealthKit (1 kcal = 4.184 kJ).
KJ_PER_KCAL = 4.184

# Allowed units — fail-loud na nieoczekiwany format (np. "oz"/"lb"/"watts").
# Lowercase porównanie po `_normalize_units`. `None` w secie = HAE legacy
# payloads bez `units` na poziomie metric (fallback do interpretacji
# domyślnej dla danej metryki — energia → kcal, masa → kg etc.).
ENERGY_UNITS: set[str | None] = {
    "kcal",
    "kilocalorie",
    "kilocalories",
    "kj",
    "kilojoule",
    "kilojoules",
    None,
}
ENERGY_KJ_UNITS: set[str] = {"kj", "kilojoule", "kilojoules"}
COUNT_UNITS: set[str | None] = {"count", None}
MS_UNITS: set[str | None] = {"ms", "millisecond", "milliseconds", None}
BPM_UNITS: set[str | None] = {"count/min", "bpm", None}
GRAM_UNITS: set[str | None] = {"g", "gram", "grams", None}
KG_UNITS: set[str | None] = {"kg", "kilogram", "kilograms", None}
PCT_UNITS: set[str | None] = {"%", "percent", None}


def _normalize_units(units: str | None) -> str | None:
    """Lowercase + strip dla forward-compat porównania.

    HAE może wysyłać `kJ ` (trailing space) albo `KCal` (mixed case) —
    `units.strip().lower()` daje stabilne porównanie z `*_UNITS` setami.
    """
    if units is None:
        return None
    return units.strip().lower()


def _validate_units(units: str | None, allowed: set[str | None], *, metric_name: str) -> None:
    """Fail-loud przy nieznanej jednostce — chroni przed silent corruption.

    Raise `ValueError` żeby `ingest()` złapało w `_safe_ingest_metric` per-point
    error handler (jeden bad point nie blokuje batcha; reszta metryk dalej leci).
    """
    norm = _normalize_units(units)
    if norm not in allowed:
        raise ValueError(
            f"unsupported units {units!r} for metric {metric_name!r}; allowed={sorted(str(u) for u in allowed)}"
        )


def _convert_energy_to_kcal(qty: float, units: str | None) -> float:
    """Konwertuje energię z HAE → kcal.

    HAE iOS eksportuje energię w **kJ** (HealthKit SI base unit). Live evidence
    2026-05-07: `kcal_in=3594.89` zapisane jako "kcal" → / 4.184 = 859 kcal,
    match z Apple Health UI.

    `units in {kcal, kilocalorie, None}` → passthrough (`None` = legacy
    fixtures bez explicit units, traktujemy jak kcal dla backward-compat).
    `units in {kJ, kilojoule}` → `qty / 4.184`.
    Inne → ValueError (caller validates upfront przez `_validate_units`).
    """
    norm = _normalize_units(units)
    if norm in ENERGY_KJ_UNITS:
        return qty / KJ_PER_KCAL
    # passthrough — kcal lub None (legacy fixtures bez units)
    return qty


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


MetricHandler = Callable[[str, dict[str, Any], datetime, str | None], bool]


def _ingest_hrv(
    user_id: str, raw: dict[str, Any], ingested_at: datetime, units: str | None
) -> bool:
    """HRV: multi-point per dzień (HAE wysyła ~10-24 readings/dzień).

    SK z timestampem dla idempotency — replay tego samego point = NOOP.
    Atrybut `value_ms` w czytelnej jednostce.
    """
    _validate_units(units, MS_UNITS, metric_name="heart_rate_variability")
    point = HAEScalarPoint.model_validate(raw)
    sk = f"BIOMETRY#{_local_date_iso(point.date)}#hrv#{point.date.isoformat()}"
    attrs = {"value_ms": point.qty, **_common_attrs(point, ingested_at)}
    return put_item_idempotent(f"USER#{user_id}", sk, attrs)


def _ingest_steps(
    user_id: str, raw: dict[str, Any], ingested_at: datetime, units: str | None
) -> bool:
    """Kroki: cumulative multi-point (HAE iOS `Aggregation: Hour`).

    SK z timestampem hourly bucketu — replay = idempotent NOOP. Sumę dzienną
    czyta `sum_metric_today` na żądanie (nie materialized — KISS).
    """
    _validate_units(units, COUNT_UNITS, metric_name="step_count")
    point = HAEScalarPoint.model_validate(raw)
    sk = f"BIOMETRY#{_local_date_iso(point.date)}#steps#{point.date.isoformat()}"
    attrs = {"count": int(point.qty), **_common_attrs(point, ingested_at)}
    return put_item_idempotent(f"USER#{user_id}", sk, attrs)


def _make_scalar_upsert(
    short_name: str, value_key: str, *, allowed_units: set[str | None], metric_name: str
) -> MetricHandler:
    """Factory dla mapperów snapshot upsert: weight, body_fat, resting_hr.

    HAE wysyła sumaryczny punkt po pomiarze — replay/follow-up payload =
    overwrite OK. SK bez timestamp.

    `allowed_units` — set jednostek które akceptujemy (fail-loud na resztę).
    `metric_name` — używane w komunikacie błędu walidacji.
    """

    def _ingest(
        user_id: str, raw: dict[str, Any], ingested_at: datetime, units: str | None
    ) -> bool:
        _validate_units(units, allowed_units, metric_name=metric_name)
        point = HAEScalarPoint.model_validate(raw)
        sk = f"BIOMETRY#{_local_date_iso(point.date)}#{short_name}"
        attrs = {value_key: point.qty, **_common_attrs(point, ingested_at)}
        put_item(f"USER#{user_id}", sk, attrs)
        return True

    return _ingest


def _make_scalar_cumulative(
    short_name: str,
    value_key: str,
    *,
    allowed_units: set[str | None],
    metric_name: str,
    energy_conversion: bool = False,
) -> MetricHandler:
    """Factory dla mapperów cumulative multi-point (hourly buckets).

    HAE iOS z `Aggregation: Hour` wysyła N punktów / dzień (każdy = delta
    tej godziny). SK z timestampem żeby każdy bucket był osobnym item.
    Replay tego samego point = idempotent NOOP (conditional PutItem).

    Sumy dzienne czyta `shared.dynamo.sum_metric_today` — read-time
    aggregation, brak materialized view (per ADR-006 trade-off).

    `energy_conversion=True` — qty traktowane jako energia, w razie potrzeby
    konwertowane kJ→kcal (HealthKit eksportuje w SI). Storage zawsze w kcal.
    """

    def _ingest(
        user_id: str, raw: dict[str, Any], ingested_at: datetime, units: str | None
    ) -> bool:
        _validate_units(units, allowed_units, metric_name=metric_name)
        point = HAEScalarPoint.model_validate(raw)
        qty = _convert_energy_to_kcal(point.qty, units) if energy_conversion else point.qty
        sk = f"BIOMETRY#{_local_date_iso(point.date)}#{short_name}#{point.date.isoformat()}"
        attrs = {value_key: qty, **_common_attrs(point, ingested_at)}
        return put_item_idempotent(f"USER#{user_id}", sk, attrs)

    return _ingest


def _ingest_heart_rate(
    user_id: str, raw: dict[str, Any], ingested_at: datetime, units: str | None
) -> bool:
    """`heart_rate` per okno czasowe — Min/Avg/Max. Multi-point z timestampem,
    idempotent. Storage: 3 wartości per row, advisor czyta avg dziennie.
    """
    _validate_units(units, BPM_UNITS, metric_name="heart_rate")
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


def _ingest_sleep(
    user_id: str, raw: dict[str, Any], ingested_at: datetime, units: str | None
) -> bool:
    """`sleep_analysis` summary per noc. Single-point per dzień, upsert.

    HAE wysyła sumaryczne wartości (inBed, asleep, core, rem, deep, awake)
    po przebudzeniu. Replay = overwrite (nowa noc nadpisze, ale w praktyce
    HAE wysyła raz, po wstaniu).
    """
    del units  # sleep ma swoje sub-fields w hrs, brak top-level units
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


METRIC_HANDLERS: dict[str, MetricHandler] = {
    # cumulative multi-point z timestamp w SK (idempotent, sum read-time)
    "heart_rate_variability": _ingest_hrv,
    "heart_rate": _ingest_heart_rate,
    "step_count": _ingest_steps,
    # 3 energy mappery z konwersją kJ→kcal (HealthKit SI base unit)
    "active_energy": _make_scalar_cumulative(
        "kcal_active",
        "kcal",
        allowed_units=ENERGY_UNITS,
        metric_name="active_energy",
        energy_conversion=True,
    ),
    "basal_energy_burned": _make_scalar_cumulative(
        "kcal_basal",
        "kcal",
        allowed_units=ENERGY_UNITS,
        metric_name="basal_energy_burned",
        energy_conversion=True,
    ),
    "dietary_energy": _make_scalar_cumulative(
        "kcal_in",
        "kcal",
        allowed_units=ENERGY_UNITS,
        metric_name="dietary_energy",
        energy_conversion=True,
    ),
    # 3 macro mappery — gramy, fail-loud na "oz"/"lb"
    "protein": _make_scalar_cumulative(
        "protein", "g", allowed_units=GRAM_UNITS, metric_name="protein"
    ),
    "total_fat": _make_scalar_cumulative(
        "fat", "g", allowed_units=GRAM_UNITS, metric_name="total_fat"
    ),
    "carbohydrates": _make_scalar_cumulative(
        "carbs", "g", allowed_units=GRAM_UNITS, metric_name="carbohydrates"
    ),
    # snapshot single-point (last-writer-wins; HAE wysyła sumaryczny punkt)
    "sleep_analysis": _ingest_sleep,
    "resting_heart_rate": _make_scalar_upsert(
        "resting_hr", "bpm", allowed_units=BPM_UNITS, metric_name="resting_heart_rate"
    ),
    "weight_body_mass": _make_scalar_upsert(
        "weight", "kg", allowed_units=KG_UNITS, metric_name="weight_body_mass"
    ),
    "body_fat_percentage": _make_scalar_upsert(
        "body_fat", "pct", allowed_units=PCT_UNITS, metric_name="body_fat_percentage"
    ),
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
                stored = handler(user_id, raw_point, ingested_at, metric.units)
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
