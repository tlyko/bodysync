"""Pure adaptive TDEE recalculation — bez DDB / SSM / boto3.

Algorithm per ADR-008 sec 1: porównaj actual waga drift z expected na bazie
formula `(kcal_in_avg - tdee_current) × 14`. Różnica / 14 to korekta TDEE
per day. Clamp ±150 kcal/iter (safety per iteration) + absolute clamp do
[baseline × 0.7, baseline × 1.5] (chroni przed propagacją bug danych).

Pure function — handler (PR2) dostarcza window z DDB Query, persist w
PROFILE row (`tdee_adaptive`, `tdee_last_recalc`, `tdee_history`).

Znak adjustment: jeśli schudłem MNIEJ niż formuła przewidywała
(`actual_delta > expected_delta` w sensie algebraicznym, oba ujemne dla
deficytu), TDEE current było przeszacowane → adjustment ujemny:

    adjustment = (expected_delta - actual_delta) / 14

Owner zatwierdził inwersję w ADR-008 sec 1 (test_normal_recalc_lowers_*).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from handlers.tdee_recalc.schemas import BiometryWindow, RecalcResult

SkipReason = Literal[
    "insufficient_kcal_data",
    "insufficient_weight_data",
    "weight_anchor_missing",
    "weight_now_missing",
    "kcal_in_avg_unrealistic",
]

# Minimum dni z danym typem biometrii w window — poniżej skip.
MIN_DATA_POINTS = 10
# Window analizy w dniach (anchor = today - WINDOW_DAYS).
WINDOW_DAYS = 14
# Przybliżenie energetyczne: 1 kg masy = 7700 kcal (fat-only approximation,
# real value 7200-7800 dla pure fat loss, ~1800 dla lean mass — clamp ±150
# kcal/iter chroni przed propagacją tej nieprecyzyjności).
KCAL_PER_KG = 7700
# Cap pojedynczej korekty per iteracja (kcal). Owner widzi max ±150 zmianę
# w 14d, anti-overshoot przy false positive (cheat weekend / hydration).
ADJUSTMENT_CAP = 150
# Absolute safety clamp — `tdee_adaptive` nigdy nie wyjdzie poza ten zakres
# vs `tdee_baseline` (Mifflin × multiplier). Chroni przed broken data
# scenario (np. kcal_in pipeline zerowy przez tydzień).
BASELINE_FLOOR_PCT = 0.7
BASELINE_CEILING_PCT = 1.5
# Pojedynczy dzień z `kcal_in < 500` traktowany jako missing (HAE drop /
# user nic nie wpisał). Drop przed liczeniem MIN_DATA_POINTS.
KCAL_IN_FLOOR = 500
# Sanity guard po winsorize — jeśli średnia < 1000 to broken data, NIE
# głodówka real-life (głodówka 1000 kcal/dzień przez 14d = case medyczny,
# nie scenariusz Recalc TDEE). Skip zamiast adjustment.
KCAL_IN_AVG_REALISTIC_FLOOR = 1000
# ±N dni od (today - 14d) szukamy waga anchor (chroni przed dniem bez
# pomiaru, ale nie sięga poza realistyczny range).
WEIGHT_ANCHOR_WINDOW_DAYS = 2
# Last weight musi być z tego window — chroni przed użyciem starej wagi
# jako "now" (właściciel nie ważył się od tygodnia → skip, nie szacuj).
WEIGHT_NOW_WINDOW_DAYS = 3
# Winsorize percentage — drop top/bottom 10% przed mean. Dla 14d = drop
# 1 najwyższego (cheat day) + 1 najniższego (broken/sick day).
WINSORIZE_PCT = 0.10
# FIFO cap dla `tdee_history` (consumed w PR2 handler logic). Stała tu
# żeby cała konfiguracja była w jednym miejscu.
HISTORY_CAP = 20


def winsorized_mean(values: list[int] | list[float], pct: float = WINSORIZE_PCT) -> float:
    """Mean po dropie `pct` najwyższych i `pct` najniższych elementów.

    Dla 14 elementów × 0.10 = `int(1.4) = 1` — drop 1 top + 1 bottom,
    mean z 12. Dla 11 elementów × 0.10 = `int(1.1) = 1` — drop 1 + 1,
    mean z 9. Pusty input lub po dropie 0 elementów to bug callerów —
    raise `ValueError` zamiast `ZeroDivisionError`.
    """
    if not values:
        raise ValueError("winsorized_mean: empty input")
    sorted_vals = sorted(values)
    drop = int(len(sorted_vals) * pct)
    trimmed = sorted_vals[drop : len(sorted_vals) - drop] if drop > 0 else sorted_vals
    if not trimmed:
        raise ValueError("winsorized_mean: pct dropped all values")
    return sum(trimmed) / len(trimmed)


def _find_weight_anchor(
    weights: list[tuple[date, float]],
    target: date,
    window_days: int = WEIGHT_ANCHOR_WINDOW_DAYS,
) -> tuple[date, float] | None:
    """Najbliższy waga point do `target` w window ±`window_days` dni.

    Tie-break: starszy z dwóch równo-blisko (sortujemy po dacie ASC przed
    `min`, więc Python pierwszego trafia). Defensive: nie zakładamy że
    handler dostarcza posortowane wejście.
    """
    in_window = sorted(
        [(d, kg) for d, kg in weights if abs((d - target).days) <= window_days],
        key=lambda pair: pair[0],
    )
    if not in_window:
        return None
    return min(in_window, key=lambda pair: abs((pair[0] - target).days))


def _find_weight_now(
    weights: list[tuple[date, float]],
    today: date,
    window_days: int = WEIGHT_NOW_WINDOW_DAYS,
) -> tuple[date, float] | None:
    """Najnowszy waga z last `window_days` dni (włącznie z dzisiaj).

    None gdy żaden point nie mieści się w window — handler zwraca skip
    `weight_now_missing` (właściciel nie ważył się od tygodnia, nie ma
    co szacować).
    """
    fresh = [(d, kg) for d, kg in weights if 0 <= (today - d).days <= window_days]
    if not fresh:
        return None
    return max(fresh, key=lambda pair: pair[0])


def _filter_kcal_window(
    kcals: list[tuple[date, int]], today: date, window_days: int = WINDOW_DAYS
) -> list[int]:
    """Tylko kcal points z last `window_days` dni i `>= KCAL_IN_FLOOR`.

    Floor 500 dropuje broken days (HAE outage, user nic nie zapisał).
    Sumowanie / agregacja per-dzień jest responsibility handlera (PR2
    czyta `BIOMETRY#{date}#kcal_in#{ts}` cumulative bucket — handler
    sumuje + grupuje per date przed dostarczeniem do `BiometryWindow`).
    """
    cutoff = today - timedelta(days=window_days)
    return [kcal for d, kcal in kcals if cutoff <= d <= today and kcal >= KCAL_IN_FLOOR]


def _filter_weight_window(
    weights: list[tuple[date, float]], today: date, window_days: int = WINDOW_DAYS
) -> list[tuple[date, float]]:
    """Tylko waga points z last `window_days` dni (inclusive)."""
    cutoff = today - timedelta(days=window_days)
    return [(d, kg) for d, kg in weights if cutoff <= d <= today]


def _make_skipped(
    *,
    reason: SkipReason,
    tdee_before: int,
    kcal_in_avg: int | None = None,
    waga_delta_kg: float | None = None,
) -> RecalcResult:
    """Helper — RecalcResult dla skipped iteration (DRY).

    `tdee_after = tdee_before` (no-op), `adjustment=None`, `capped=False`.
    """
    return RecalcResult(
        ok=True,
        skipped=True,
        reason=reason,
        tdee_before=tdee_before,
        tdee_after=tdee_before,
        kcal_in_avg=kcal_in_avg,
        waga_delta_kg=waga_delta_kg,
        adjustment=None,
        capped=False,
    )


def recalculate_tdee(
    *,
    today: date,
    baseline: int,
    current: int,
    window: BiometryWindow,
) -> RecalcResult:
    """Pure function — porównuje expected vs actual waga drift, zwraca korektę.

    `baseline` = Mifflin × activity_multiplier (immutable per body_profile).
    `current` = obecne `tdee_adaptive` (= baseline jeśli pierwsza iteracja).
    `window` = surowe waga + kcal points z last 14d (handler zbiera z DDB).

    Zwraca `RecalcResult` z `tdee_after` do persistowania w PROFILE row.
    `skipped=True` to expected scenario (insufficient data / sanity guard) —
    handler zwraca 200 z body, NIE 400.
    """
    weights_in_window = _filter_weight_window(window.weights, today)
    kcals_in_window = _filter_kcal_window(window.kcals, today)

    if len(kcals_in_window) < MIN_DATA_POINTS:
        return _make_skipped(reason="insufficient_kcal_data", tdee_before=current)

    if len(weights_in_window) < MIN_DATA_POINTS:
        return _make_skipped(reason="insufficient_weight_data", tdee_before=current)

    weight_now = _find_weight_now(weights_in_window, today)
    if weight_now is None:
        return _make_skipped(reason="weight_now_missing", tdee_before=current)

    anchor_target = today - timedelta(days=WINDOW_DAYS)
    weight_anchor = _find_weight_anchor(weights_in_window, anchor_target)
    if weight_anchor is None:
        return _make_skipped(reason="weight_anchor_missing", tdee_before=current)

    kcal_in_avg_raw = winsorized_mean(kcals_in_window)
    kcal_in_avg = int(round(kcal_in_avg_raw))

    if kcal_in_avg < KCAL_IN_AVG_REALISTIC_FLOOR:
        return _make_skipped(
            reason="kcal_in_avg_unrealistic",
            tdee_before=current,
            kcal_in_avg=kcal_in_avg,
        )

    waga_delta_kg = weight_now[1] - weight_anchor[1]

    expected_delta_kcal = (kcal_in_avg - current) * WINDOW_DAYS
    actual_delta_kcal = waga_delta_kg * KCAL_PER_KG
    adjustment_raw = (expected_delta_kcal - actual_delta_kcal) / WINDOW_DAYS

    capped = abs(adjustment_raw) > ADJUSTMENT_CAP
    adjustment = max(-ADJUSTMENT_CAP, min(ADJUSTMENT_CAP, adjustment_raw))
    adjustment_int = int(round(adjustment))

    tdee_new = current + adjustment_int
    floor = int(round(baseline * BASELINE_FLOOR_PCT))
    ceiling = int(round(baseline * BASELINE_CEILING_PCT))
    tdee_new_clamped = max(floor, min(ceiling, tdee_new))

    return RecalcResult(
        ok=True,
        skipped=False,
        reason=None,
        tdee_before=current,
        tdee_after=tdee_new_clamped,
        kcal_in_avg=kcal_in_avg,
        waga_delta_kg=round(waga_delta_kg, 3),
        adjustment=adjustment_int,
        capped=capped,
    )
