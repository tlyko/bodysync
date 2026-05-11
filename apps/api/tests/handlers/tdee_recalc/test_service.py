"""Unit testy dla `tdee_recalc.service.recalculate_tdee` (pure function).

Każdy test ma konkretne wejście i sprawdza konkretną wartość wyjścia.
Test 1 to smoking gun na znak `adjustment = (expected - actual) / 14`
z ADR-008 sec 1 — jeśli architect się mylił, ten test failuje pierwszy.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from handlers.tdee_recalc.schemas import BiometryWindow
from handlers.tdee_recalc.service import (
    recalculate_tdee,
    winsorized_mean,
)

TODAY = date(2026, 5, 11)
WINDOW_START = date(2026, 4, 28)
ANCHOR_DATE = date(2026, 4, 27)
BASELINE = 2280
CURRENT = 2280


def _kcal_list(start: date, days: int, kcal: int | list[int]) -> list[tuple[date, int]]:
    if isinstance(kcal, int):
        return [(start + timedelta(days=i), kcal) for i in range(days)]
    return [(start + timedelta(days=i), kcal[i]) for i in range(days)]


def _weight_list(start: date, days: int, kg: float | list[float]) -> list[tuple[date, float]]:
    if isinstance(kg, list):
        return [(start + timedelta(days=i), kg[i]) for i in range(days)]
    return [(start + timedelta(days=i), kg) for i in range(days)]


def _make_window(
    *,
    weights: list[tuple[date, float]] | None = None,
    kcals: list[tuple[date, int]] | None = None,
) -> BiometryWindow:
    return BiometryWindow(
        weights=weights or [],
        kcals=kcals or [],
    )


def test_normal_recalc_lowers_tdee_when_actual_loss_less_than_expected() -> None:
    """ADR-008 sec 1 smoking gun na znak adjustment.

    Owner zjadł deficyt 200 kcal/dzień przez 14d (kcal_in 2080 vs tdee 2280).
    Waga zero zmiany → expected_delta=-2800, actual_delta=0.
    adjustment = (expected - actual) / 14 = -200, clamped do -150.
    Sens: jadłem deficyt ale waga zero = TDEE było przeszacowane → obniż.
    """
    window = _make_window(
        weights=_weight_list(WINDOW_START, 14, 80.0),
        kcals=_kcal_list(WINDOW_START, 14, 2080),
    )
    result = recalculate_tdee(today=TODAY, baseline=BASELINE, current=CURRENT, window=window)

    assert result.skipped is False
    assert result.reason is None
    assert result.adjustment == -150
    assert result.capped is True
    assert result.tdee_before == 2280
    assert result.tdee_after == 2130
    assert result.kcal_in_avg == 2080
    assert result.waga_delta_kg == 0.0


def test_normal_recalc_raises_tdee_when_actual_loss_more_than_expected() -> None:
    """Deficyt 200/dzień + waga -1 kg = schudłem WIĘCEJ niż formuła.

    expected_delta=-2800, actual_delta=-7700.
    adjustment = (expected - actual) / 14 = (-2800 - (-7700))/14 = +350, clamped +150.
    Sens: schudłem mimo że nie powinienem aż tyle = TDEE było zaniżone → podnieś.
    """
    weights = [
        (WINDOW_START, 80.0),
        (WINDOW_START + timedelta(days=1), 80.0),
        (WINDOW_START + timedelta(days=2), 80.0),
        (WINDOW_START + timedelta(days=3), 80.0),
        (WINDOW_START + timedelta(days=4), 80.0),
        (WINDOW_START + timedelta(days=5), 79.5),
        (WINDOW_START + timedelta(days=6), 79.5),
        (WINDOW_START + timedelta(days=7), 79.5),
        (WINDOW_START + timedelta(days=8), 79.5),
        (WINDOW_START + timedelta(days=9), 79.0),
        (WINDOW_START + timedelta(days=10), 79.0),
        (WINDOW_START + timedelta(days=11), 79.0),
        (WINDOW_START + timedelta(days=12), 79.0),
        (TODAY, 79.0),
    ]
    window = _make_window(
        weights=weights,
        kcals=_kcal_list(WINDOW_START, 14, 2080),
    )
    result = recalculate_tdee(today=TODAY, baseline=BASELINE, current=CURRENT, window=window)

    assert result.skipped is False
    assert result.adjustment == 150
    assert result.capped is True
    assert result.tdee_after == 2430
    assert result.waga_delta_kg == -1.0


def test_insufficient_kcal_data_skipped() -> None:
    """Tylko 8 dni kcal_in (< MIN_DATA_POINTS=10) → skip."""
    window = _make_window(
        weights=_weight_list(WINDOW_START, 14, 80.0),
        kcals=_kcal_list(WINDOW_START, 8, 2080),
    )
    result = recalculate_tdee(today=TODAY, baseline=BASELINE, current=CURRENT, window=window)

    assert result.skipped is True
    assert result.reason == "insufficient_kcal_data"
    assert result.tdee_after == CURRENT
    assert result.adjustment is None


def test_insufficient_weight_data_skipped() -> None:
    """Tylko 8 wag w 14d → skip."""
    window = _make_window(
        weights=_weight_list(WINDOW_START, 8, 80.0),
        kcals=_kcal_list(WINDOW_START, 14, 2080),
    )
    result = recalculate_tdee(today=TODAY, baseline=BASELINE, current=CURRENT, window=window)

    assert result.skipped is True
    assert result.reason == "insufficient_weight_data"
    assert result.tdee_after == CURRENT


def test_weight_anchor_missing_skipped() -> None:
    """14 wag ale wszystkie z last 5 dni — anchor sprzed 14d nie istnieje."""
    weights_recent_only = [
        (TODAY - timedelta(days=4), 80.0),
        (TODAY - timedelta(days=4), 80.0),
        (TODAY - timedelta(days=3), 80.0),
        (TODAY - timedelta(days=3), 80.0),
        (TODAY - timedelta(days=2), 80.0),
        (TODAY - timedelta(days=2), 80.0),
        (TODAY - timedelta(days=1), 80.0),
        (TODAY - timedelta(days=1), 80.0),
        (TODAY - timedelta(days=1), 80.0),
        (TODAY, 80.0),
        (TODAY, 80.0),
        (TODAY, 80.0),
        (TODAY, 80.0),
        (TODAY, 80.0),
    ]
    window = _make_window(
        weights=weights_recent_only,
        kcals=_kcal_list(WINDOW_START, 14, 2080),
    )
    result = recalculate_tdee(today=TODAY, baseline=BASELINE, current=CURRENT, window=window)

    assert result.skipped is True
    assert result.reason == "weight_anchor_missing"


def test_weight_now_missing_skipped() -> None:
    """14 wag ale ostatnia z 5 dni temu (poza WEIGHT_NOW_WINDOW_DAYS=3)."""
    weights_old_only = _weight_list(WINDOW_START, 9, 80.0) + [
        (TODAY - timedelta(days=5), 80.0),
        (TODAY - timedelta(days=5), 80.0),
        (TODAY - timedelta(days=5), 80.0),
        (TODAY - timedelta(days=5), 80.0),
        (TODAY - timedelta(days=5), 80.0),
    ]
    window = _make_window(
        weights=weights_old_only,
        kcals=_kcal_list(WINDOW_START, 14, 2080),
    )
    result = recalculate_tdee(today=TODAY, baseline=BASELINE, current=CURRENT, window=window)

    assert result.skipped is True
    assert result.reason == "weight_now_missing"


def test_kcal_in_avg_below_realistic_floor_skipped() -> None:
    """Wszystkie dni z kcal_in 700 (avg po winsorize = 700 < 1000) → skip broken data."""
    window = _make_window(
        weights=_weight_list(WINDOW_START, 14, 80.0),
        kcals=_kcal_list(WINDOW_START, 14, 700),
    )
    result = recalculate_tdee(today=TODAY, baseline=BASELINE, current=CURRENT, window=window)

    assert result.skipped is True
    assert result.reason == "kcal_in_avg_unrealistic"
    assert result.kcal_in_avg == 700


def test_winsorize_drops_top_and_bottom_10pct() -> None:
    """14 dni: 12 × 2000, 1 × 4000 (cheat day), 1 × 600 (broken-but-not-dropped).

    Floor 500: 600 zostaje przed winsorize.
    Winsorize 10% × 14 = int(1.4) = 1 → drop 1 top (4000) + 1 bottom (600) =
    mean z 12 = 2000.
    """
    kcals_data = [2000] * 12 + [4000, 600]
    window = _make_window(
        weights=_weight_list(WINDOW_START, 14, 80.0),
        kcals=_kcal_list(WINDOW_START, 14, kcals_data),
    )
    result = recalculate_tdee(today=TODAY, baseline=BASELINE, current=CURRENT, window=window)

    assert result.kcal_in_avg == 2000


def test_clamp_per_iteration_caps_extreme_adjustment() -> None:
    """Waga -3 kg w 14d (extremalna) → adjustment cap'd ±150."""
    weights = _weight_list(WINDOW_START, 13, 80.0) + [(TODAY, 77.0)]
    window = _make_window(
        weights=weights,
        kcals=_kcal_list(WINDOW_START, 14, 2080),
    )
    result = recalculate_tdee(today=TODAY, baseline=BASELINE, current=CURRENT, window=window)

    assert result.adjustment is not None
    assert abs(result.adjustment) == 150
    assert result.capped is True


def test_absolute_safety_floor_blocks_baseline_below_70pct() -> None:
    """Current=1700 (po hist iteracjach), adjustment -150 → tdee_new=1550 < floor=1596."""
    window = _make_window(
        weights=_weight_list(WINDOW_START, 14, 80.0),
        kcals=_kcal_list(WINDOW_START, 14, 1500),
    )
    result = recalculate_tdee(today=TODAY, baseline=BASELINE, current=1700, window=window)

    floor = int(round(BASELINE * 0.7))
    assert result.tdee_after == floor
    assert result.adjustment == -150


def test_absolute_safety_ceiling_blocks_baseline_above_150pct() -> None:
    """Current=3370, adjustment +150 → tdee_new=3520 > ceiling=3420."""
    window = _make_window(
        weights=_weight_list(WINDOW_START, 14, 80.0),
        kcals=_kcal_list(WINDOW_START, 14, 4000),
    )
    result = recalculate_tdee(today=TODAY, baseline=BASELINE, current=3370, window=window)

    ceiling = int(round(BASELINE * 1.5))
    assert result.tdee_after == ceiling
    assert result.adjustment == 150


def test_kcal_in_below_500_dropped_as_missing_day() -> None:
    """5 dni z 300 (< KCAL_IN_FLOOR), 9 dni z 2000 → 9 < 10 → skip."""
    kcals_data = [300] * 5 + [2000] * 9
    window = _make_window(
        weights=_weight_list(WINDOW_START, 14, 80.0),
        kcals=_kcal_list(WINDOW_START, 14, kcals_data),
    )
    result = recalculate_tdee(today=TODAY, baseline=BASELINE, current=CURRENT, window=window)

    assert result.skipped is True
    assert result.reason == "insufficient_kcal_data"


def test_winsorized_mean_with_small_list() -> None:
    """Helper test directly. 11 elementów × 10% = drop 1+1, mean z 9."""
    values: list[int] = [1000] + [2000] * 9 + [4000]
    result = winsorized_mean(values)
    assert result == 2000.0


def test_recalc_result_capped_flag_true_when_adjustment_was_capped() -> None:
    """Jak test 1 — assert specifically capped=True."""
    window = _make_window(
        weights=_weight_list(WINDOW_START, 14, 80.0),
        kcals=_kcal_list(WINDOW_START, 14, 2080),
    )
    result = recalculate_tdee(today=TODAY, baseline=BASELINE, current=CURRENT, window=window)
    assert result.capped is True


def test_recalc_result_capped_flag_false_when_within_bounds() -> None:
    """Waga -0.3 kg, deficyt 100 → adjustment ~+65 (within ±150) → capped=False."""
    weights = _weight_list(WINDOW_START, 13, 80.0) + [(TODAY, 79.7)]
    window = _make_window(
        weights=weights,
        kcals=_kcal_list(WINDOW_START, 14, 2180),
    )
    result = recalculate_tdee(today=TODAY, baseline=BASELINE, current=CURRENT, window=window)

    assert result.capped is False
    assert result.adjustment is not None
    assert -150 < result.adjustment < 150


def test_baseline_above_floor_below_ceiling_pass_through() -> None:
    """Normal scenario z adjustment ~+30, tdee_new ~2310 ∈ [1596, 3420], unchanged."""
    weights = _weight_list(WINDOW_START, 13, 80.0) + [(TODAY, 79.86)]
    window = _make_window(
        weights=weights,
        kcals=_kcal_list(WINDOW_START, 14, 2230),
    )
    result = recalculate_tdee(today=TODAY, baseline=BASELINE, current=CURRENT, window=window)

    assert result.skipped is False
    assert result.capped is False
    assert result.tdee_after == CURRENT + (result.adjustment or 0)


def test_winsorized_mean_empty_raises() -> None:
    """Defensive: pusty input to bug callerów, raise zamiast ZeroDivisionError."""
    with pytest.raises(ValueError, match="empty input"):
        winsorized_mean([])
