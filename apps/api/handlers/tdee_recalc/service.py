"""Pure diet check evaluation — bez DDB / SSM / boto3 / LLM.

Algorithm per ADR-009 sec 1: porównaj actual waga drift z expected na
bazie owner's `kcal_target` (MANUAL goal — z `ProfileTargetsForm` lub
TDEE wizard "Zastosuj do moich celów"). Status classification trzy-tier
(`on_track` / `too_fast` / `too_slow_or_gain`) → handler woła LLM Haiku
z hintem żeby napisać natural PL narrative.

Pure function — handler dostarcza window z DDB, persist `diet_check_history`
w PROFILE, opcjonalnie wywołuje LLM (PR2). Drop adaptive TDEE concept
(Mifflin baseline + clamping) — owner's `kcal_target` jest authoritative.

Znak `expected_delta`:
    deficit_per_day = goal_kcal - kcal_in_avg   # >0 jeśli jadłem poniżej target
    expected_delta_kg = -deficit_per_day * 14 / 7700
    # ujemne = oczekiwana strata wagi (deficit przez 14d)
"""

from __future__ import annotations

from datetime import date, timedelta

from handlers.tdee_recalc.schemas import (
    BiometryWindow,
    DietCheckHistoryEntry,
    DietCheckResult,
    DietCheckSkipReason,
    DietCheckStatus,
)

# Minimum dni z danym typem biometrii w window — poniżej skip.
MIN_DATA_POINTS = 10
# Window analizy w dniach (anchor = today - WINDOW_DAYS).
WINDOW_DAYS = 14
# Przybliżenie energetyczne: 1 kg masy = 7700 kcal (fat-only approximation,
# lean mass loss to ~1800/kg). Akceptujemy nieprecyzyjność — i tak
# klasyfikacja statusu używa szerokich progów (0.3-0.5 kg).
KCAL_PER_KG = 7700
# Próg `on_track` — |diff| < 0.3 kg w 14d traktujemy jako "zgodnie z planem".
ON_TRACK_THRESHOLD_KG = 0.3
# Próg `too_fast` — actual loss przewyższa expected o > 0.5 kg = za szybko.
TOO_FAST_THRESHOLD_KG = 0.5
# Pojedynczy dzień z `kcal_in < 500` traktowany jako missing (HAE drop).
KCAL_IN_FLOOR = 500
# ±N dni od (today - 14d) szukamy waga anchor.
WEIGHT_ANCHOR_WINDOW_DAYS = 2
# Last weight musi być z tego window.
WEIGHT_NOW_WINDOW_DAYS = 3
# Winsorize percentage — drop top/bottom 10% przed mean.
WINSORIZE_PCT = 0.10
# FIFO cap dla `diet_check_history` (handler logic).
HISTORY_CAP = 10


def winsorized_mean(values: list[int] | list[float], pct: float = WINSORIZE_PCT) -> float:
    """Mean po dropie `pct` najwyższych i `pct` najniższych elementów."""
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
    """Najbliższy waga point do `target` w window ±`window_days` dni."""
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
    """Najnowszy waga z last `window_days` dni (włącznie z dzisiaj)."""
    fresh = [(d, kg) for d, kg in weights if 0 <= (today - d).days <= window_days]
    if not fresh:
        return None
    return max(fresh, key=lambda pair: pair[0])


def _filter_kcal_window(
    kcals: list[tuple[date, int]], today: date, window_days: int = WINDOW_DAYS
) -> list[int]:
    """Tylko kcal points z last `window_days` dni i `>= KCAL_IN_FLOOR`."""
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
    reason: DietCheckSkipReason,
    goal_kcal: int | None = None,
) -> DietCheckResult:
    """Skipped iteration — narrative None, narrative_unavailable=False (LLM
    nie był wołany; nie błąd LLM).
    """
    return DietCheckResult(
        skipped=True,
        skip_reason=reason,
        goal_kcal=goal_kcal,
        kcal_in_avg=None,
        waga_now_kg=None,
        waga_then_kg=None,
        waga_delta_kg=None,
        expected_delta_kg=None,
        actual_delta_kg=None,
        diff_kg=None,
        status=None,
        narrative=None,
        narrative_unavailable=False,
    )


def classify_status(diff_kg: float) -> DietCheckStatus:
    """3-tier classification per ADR-009 sec 2 — asymmetric tolerance.

    `diff_kg = actual_delta - expected_delta` (signed). Schudnięcie więcej
    niż expected (ujemne diff) jest mniej alarmujące — bufor do -0.5 kg
    przed alarmem. Tycie / spowolnienie (dodatnie diff) reaguje już od +0.3.

    - `diff <= -0.5` → `too_fast` (wyraźnie szybciej niż plan)
    - `-0.5 < diff < +0.3` → `on_track` (asymetryczny bufor uwzględnia
      retencję i normalne wahania, akceptuje lekkie nadtempo)
    - `diff >= +0.3` → `too_slow_or_gain` (wolniej niż plan lub tycie)
    """
    if diff_kg <= -TOO_FAST_THRESHOLD_KG:
        return "too_fast"
    if diff_kg >= ON_TRACK_THRESHOLD_KG:
        return "too_slow_or_gain"
    return "on_track"


def evaluate_diet_check(
    *,
    today: date,
    kcal_target: int | None,
    window: BiometryWindow,
) -> DietCheckResult:
    """Pure function — porównuje expected vs actual waga drift vs MANUAL goal.

    `kcal_target` = owner's kcal goal z PROFILE (manual lub wizard apply).
    None → skipped `no_kcal_target` (PROFILE row brak `kcal_target` field —
    sytuacja nietypowa, login flow zapisuje default fallback).

    Per ADR-009 sec 1 — drop Mifflin clamping i adjustment cap. `kcal_target`
    jest authoritative. Owner może mieć dowolnie agresywny lub konserwatywny
    cel — algorithm tylko oblicza expected vs actual.
    """
    if kcal_target is None:
        return _make_skipped(reason="no_kcal_target")

    weights_in_window = _filter_weight_window(window.weights, today)
    kcals_in_window = _filter_kcal_window(window.kcals, today)

    if len(kcals_in_window) < MIN_DATA_POINTS:
        return _make_skipped(reason="insufficient_kcal_data", goal_kcal=kcal_target)

    if len(weights_in_window) < MIN_DATA_POINTS:
        return _make_skipped(reason="insufficient_weight_data", goal_kcal=kcal_target)

    weight_now = _find_weight_now(weights_in_window, today)
    if weight_now is None:
        return _make_skipped(reason="weight_now_missing", goal_kcal=kcal_target)

    anchor_target = today - timedelta(days=WINDOW_DAYS)
    weight_anchor = _find_weight_anchor(weights_in_window, anchor_target)
    if weight_anchor is None:
        return _make_skipped(reason="weight_anchor_missing", goal_kcal=kcal_target)

    kcal_in_avg = int(round(winsorized_mean(kcals_in_window)))
    waga_now_kg = round(weight_now[1], 2)
    waga_then_kg = round(weight_anchor[1], 2)
    waga_delta_kg = round(waga_now_kg - waga_then_kg, 3)

    # Expected: jeśli kcal_in_avg < goal_kcal, jadłem poniżej celu = expected loss.
    deficit_per_day = kcal_target - kcal_in_avg
    expected_delta_kg = round(-deficit_per_day * WINDOW_DAYS / KCAL_PER_KG, 3)
    actual_delta_kg = waga_delta_kg
    diff_kg = round(actual_delta_kg - expected_delta_kg, 3)

    status = classify_status(diff_kg)

    return DietCheckResult(
        skipped=False,
        skip_reason=None,
        goal_kcal=kcal_target,
        kcal_in_avg=kcal_in_avg,
        waga_now_kg=waga_now_kg,
        waga_then_kg=waga_then_kg,
        waga_delta_kg=waga_delta_kg,
        expected_delta_kg=expected_delta_kg,
        actual_delta_kg=actual_delta_kg,
        diff_kg=diff_kg,
        status=status,
        narrative=None,
        narrative_unavailable=False,
    )


def build_diet_check_history_entry(
    *, today: date, result: DietCheckResult
) -> DietCheckHistoryEntry:
    """Z `DietCheckResult` zbuduj entry do append w `diet_check_history`.

    Storage compaction — drop `kcal_in_avg` redundant ze `goal_kcal`,
    drop `waga_now/then` (delta wystarczy dla audit). Trzymamy `narrative`
    żeby owner widział co LLM mówił poprzednio.
    """
    return DietCheckHistoryEntry(
        date=today,
        skipped=result.skipped,
        skip_reason=result.skip_reason,
        goal_kcal=result.goal_kcal,
        kcal_in_avg=result.kcal_in_avg,
        waga_delta_kg=result.waga_delta_kg,
        diff_kg=result.diff_kg,
        status=result.status,
        narrative=result.narrative,
    )


def cap_diet_check_history(
    history: list[DietCheckHistoryEntry], cap: int = HISTORY_CAP
) -> list[DietCheckHistoryEntry]:
    """FIFO cap — drop oldest gdy len > cap. Idempotent dla short list."""
    if len(history) <= cap:
        return history
    return history[-cap:]
