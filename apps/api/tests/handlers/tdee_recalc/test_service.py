"""Unit testy dla `tdee_recalc.service.evaluate_diet_check` (Sprint 11.5 ADR-009).

Pivot ze Sprint 11 — pure function compare vs MANUAL `kcal_target`,
output status classification (3-tier) + slot na LLM narrative (PR2).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from handlers.tdee_recalc.schemas import BiometryWindow
from handlers.tdee_recalc.service import (
    classify_status,
    evaluate_diet_check,
    winsorized_mean,
)

TODAY = date(2026, 5, 11)
WINDOW_START = date(2026, 4, 28)
GOAL = 2250  # owner's manual kcal_target


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
    return BiometryWindow(weights=weights or [], kcals=kcals or [])


# ─── Happy paths — 3 tier status classification ───────────────────────────


def test_on_track_when_actual_loss_matches_expected_within_threshold() -> None:
    """Owner jadł 2050 kcal/dzień (deficit 200 vs goal 2250) przez 14d.
    Expected loss: 200 * 14 / 7700 = -0.36 kg. Actual: -0.4 kg.
    Diff = -0.04, |diff| < 0.3 → on_track.
    """
    weights = _weight_list(WINDOW_START, 13, 80.0) + [(TODAY, 79.6)]
    window = _make_window(
        weights=weights,
        kcals=_kcal_list(WINDOW_START, 14, 2050),
    )
    result = evaluate_diet_check(today=TODAY, kcal_target=GOAL, window=window)

    assert result.skipped is False
    assert result.status == "on_track"
    assert result.kcal_in_avg == 2050
    assert result.waga_delta_kg == -0.4
    # expected = -(2250 - 2050) * 14 / 7700 = -0.364
    assert result.expected_delta_kg == pytest.approx(-0.364, abs=0.01)
    assert result.diff_kg == pytest.approx(-0.036, abs=0.01)


def test_too_fast_when_actual_loss_exceeds_expected_by_threshold() -> None:
    """Deficit 200/day, expected -0.36 kg, actual -1.0 kg. Diff = -0.64 → too_fast."""
    weights = _weight_list(WINDOW_START, 13, 80.0) + [(TODAY, 79.0)]
    window = _make_window(
        weights=weights,
        kcals=_kcal_list(WINDOW_START, 14, 2050),
    )
    result = evaluate_diet_check(today=TODAY, kcal_target=GOAL, window=window)

    assert result.skipped is False
    assert result.status == "too_fast"
    assert result.diff_kg == pytest.approx(-0.636, abs=0.01)


def test_too_slow_or_gain_when_actual_gain_vs_expected_loss() -> None:
    """Deficit 200/day, expected -0.36 kg, actual +0.5 kg (tycie). Diff = +0.86 → too_slow_or_gain."""
    weights = _weight_list(WINDOW_START, 13, 80.0) + [(TODAY, 80.5)]
    window = _make_window(
        weights=weights,
        kcals=_kcal_list(WINDOW_START, 14, 2050),
    )
    result = evaluate_diet_check(today=TODAY, kcal_target=GOAL, window=window)

    assert result.skipped is False
    assert result.status == "too_slow_or_gain"
    assert result.diff_kg == pytest.approx(0.864, abs=0.01)


# ─── Skip scenarios ─────────────────────────────────────────────────────────


def test_no_kcal_target_skipped() -> None:
    """PROFILE bez kcal_target (anomaly) → skip z reason."""
    window = _make_window(
        weights=_weight_list(WINDOW_START, 14, 80.0),
        kcals=_kcal_list(WINDOW_START, 14, 2050),
    )
    result = evaluate_diet_check(today=TODAY, kcal_target=None, window=window)

    assert result.skipped is True
    assert result.skip_reason == "no_kcal_target"
    assert result.status is None
    assert result.narrative is None


def test_insufficient_kcal_data_skipped() -> None:
    """Tylko 8 dni kcal_in (< MIN_DATA_POINTS=10) → skip."""
    window = _make_window(
        weights=_weight_list(WINDOW_START, 14, 80.0),
        kcals=_kcal_list(WINDOW_START, 8, 2050),
    )
    result = evaluate_diet_check(today=TODAY, kcal_target=GOAL, window=window)

    assert result.skipped is True
    assert result.skip_reason == "insufficient_kcal_data"
    assert result.goal_kcal == GOAL  # echo back


def test_insufficient_weight_data_skipped() -> None:
    """Tylko 8 wag w 14d → skip."""
    window = _make_window(
        weights=_weight_list(WINDOW_START, 8, 80.0),
        kcals=_kcal_list(WINDOW_START, 14, 2050),
    )
    result = evaluate_diet_check(today=TODAY, kcal_target=GOAL, window=window)

    assert result.skipped is True
    assert result.skip_reason == "insufficient_weight_data"


def test_weight_anchor_missing_skipped() -> None:
    """14 wag ale wszystkie z last 5 dni — anchor sprzed 14d nie istnieje."""
    weights_recent_only = [(TODAY - timedelta(days=i % 5), 80.0) for i in range(14)]
    window = _make_window(
        weights=weights_recent_only,
        kcals=_kcal_list(WINDOW_START, 14, 2050),
    )
    result = evaluate_diet_check(today=TODAY, kcal_target=GOAL, window=window)

    assert result.skipped is True
    assert result.skip_reason == "weight_anchor_missing"


def test_weight_now_missing_skipped() -> None:
    """14 wag ale ostatnia z 5 dni temu (poza WEIGHT_NOW_WINDOW_DAYS=3)."""
    weights_old_only = _weight_list(WINDOW_START, 9, 80.0) + [
        (TODAY - timedelta(days=5), 80.0) for _ in range(5)
    ]
    window = _make_window(
        weights=weights_old_only,
        kcals=_kcal_list(WINDOW_START, 14, 2050),
    )
    result = evaluate_diet_check(today=TODAY, kcal_target=GOAL, window=window)

    assert result.skipped is True
    assert result.skip_reason == "weight_now_missing"


# ─── Helpers ───────────────────────────────────────────────────────────────


def test_classify_status_thresholds() -> None:
    """Boundary checks dla 3-tier classifier (asymetryczny tolerancja)."""
    assert classify_status(0.0) == "on_track"
    assert classify_status(0.29) == "on_track"
    assert classify_status(-0.29) == "on_track"
    assert classify_status(0.31) == "too_slow_or_gain"
    assert classify_status(-0.31) == "on_track"  # bufor do -0.5 przed too_fast
    assert classify_status(-0.49) == "on_track"  # nadal w buforze
    assert classify_status(-0.5) == "too_fast"  # boundary inclusive
    assert classify_status(-0.51) == "too_fast"
    assert classify_status(1.0) == "too_slow_or_gain"


def test_winsorize_drops_top_and_bottom_10pct() -> None:
    """14 dni z 12 × 2050 + 1 × 4000 (cheat) + 1 × 600 (broken) → mean=2050."""
    kcals_data = [2050] * 12 + [4000, 600]
    window = _make_window(
        weights=_weight_list(WINDOW_START, 14, 80.0),
        kcals=_kcal_list(WINDOW_START, 14, kcals_data),
    )
    result = evaluate_diet_check(today=TODAY, kcal_target=GOAL, window=window)

    assert result.kcal_in_avg == 2050  # winsorize zignorował ekstremy


def test_winsorized_mean_empty_raises() -> None:
    """Defensive: pusty input to bug callerów, raise."""
    with pytest.raises(ValueError, match="empty input"):
        winsorized_mean([])


def test_narrative_is_none_in_pr1() -> None:
    """PR1 nie woła LLM — narrative=None, narrative_unavailable=False (NIE error,
    po prostu LLM nie był wołany jeszcze; PR2 wypełni)."""
    weights = _weight_list(WINDOW_START, 13, 80.0) + [(TODAY, 79.6)]
    window = _make_window(
        weights=weights,
        kcals=_kcal_list(WINDOW_START, 14, 2050),
    )
    result = evaluate_diet_check(today=TODAY, kcal_target=GOAL, window=window)

    assert result.narrative is None
    assert result.narrative_unavailable is False
