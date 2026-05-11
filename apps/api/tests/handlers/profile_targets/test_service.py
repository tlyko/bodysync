"""Sprint 11 PR4 testy — `update_targets` z body_profile init/change reset.

Cross-handler scope: PR4 dodaje TDEE baseline/adaptive auto-init w
istniejącym `update_targets`, gdy body_profile zostaje saved pierwszy
raz lub się zmienia (5-field diff). Wymaga waga w BIOMETRY.

Mirror w `handlers/tdee_recalc/handler.py:_persist_recalc` shape
(structural contract — zmieniasz tu, mirror tam).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest


def _seed_profile(table: Any, user_id: str, **extra_attrs: Any) -> None:
    item: dict[str, Any] = {
        "PK": f"USER#{user_id}",
        "SK": "PROFILE",
        "email": f"{user_id}@example.com",
        "name": user_id,
        **extra_attrs,
    }
    table.put_item(Item=item)


def _seed_weight(table: Any, user_id: str, *, day: str, kg: float) -> None:
    table.put_item(
        Item={
            "PK": f"USER#{user_id}",
            "SK": f"BIOMETRY#{day}#weight",
            "kg": Decimal(str(kg)),
        }
    )


@pytest.mark.usefixtures("ssm_params")
def test_first_body_profile_save_initializes_tdee_baseline_and_adaptive(
    dynamodb_table: Any,
) -> None:
    """Initial onboarding: brak tdee_baseline + nowy body_profile + waga w BIOMETRY → init."""
    from handlers.profile_targets.schemas import BodyProfile
    from handlers.profile_targets.service import update_targets

    _seed_profile(dynamodb_table, "tomek")
    _seed_weight(dynamodb_table, "tomek", day=date.today().isoformat(), kg=80.0)

    bp = BodyProfile(
        height_cm=180,
        age=30,
        sex="male",
        activity_level="moderate",
        goal="maintain",
    )
    update_targets("tomek", 9999, 99, 99, 99, body_profile=bp)

    profile = dynamodb_table.get_item(Key={"PK": "USER#tomek", "SK": "PROFILE"})["Item"]

    # BMR = 10*80 + 6.25*180 - 5*30 + 5 = 1780; TDEE = 1780 * 1.55 = 2759.0
    assert int(profile["tdee_baseline"]) == 2759
    assert int(profile["tdee_adaptive"]) == 2759
    assert profile.get("tdee_last_recalc") is None
    assert len(profile["tdee_history"]) == 1
    entry = profile["tdee_history"][0]
    assert entry["event"] == "initial"
    assert entry["before"] is None
    assert int(entry["after"]) == 2759
    # User-provided 9999 kcal_target zignorowane — auto-sync wins.
    assert int(profile["kcal_target"]) != 9999
    assert int(profile["kcal_target"]) > 2700  # ~2760 (calculate_target_kcal)


@pytest.mark.usefixtures("ssm_params")
def test_body_profile_change_resets_baseline_and_adaptive(
    dynamodb_table: Any,
) -> None:
    """Activity_level moderate→heavy → reset baseline+adaptive do nowego Mifflin'a."""
    from handlers.profile_targets.schemas import BodyProfile
    from handlers.profile_targets.service import update_targets

    _seed_profile(
        dynamodb_table,
        "tomek",
        height_cm=180,
        age=30,
        sex="male",
        activity_level="moderate",
        goal="maintain",
        tdee_baseline=2759,
        tdee_adaptive=2900,  # adaptive odjechało od baseline (po wielu recalc)
        kcal_target=2760,
        protein_target_g=145,
        fat_target_g=70,
        carbs_target_g=395,
    )
    _seed_weight(dynamodb_table, "tomek", day=date.today().isoformat(), kg=80.0)

    bp = BodyProfile(
        height_cm=180,
        age=30,
        sex="male",
        activity_level="heavy",  # zmieniona
        goal="maintain",
    )
    update_targets("tomek", 2900, 145, 70, 395, body_profile=bp)

    profile = dynamodb_table.get_item(Key={"PK": "USER#tomek", "SK": "PROFILE"})["Item"]

    # Nowy TDEE = 1780 * 1.725 = 3070.5 → 3071 (round half-to-even Python)
    new_baseline = int(profile["tdee_baseline"])
    assert new_baseline in (3070, 3071)
    assert int(profile["tdee_adaptive"]) == new_baseline  # restart pętli
    assert len(profile["tdee_history"]) == 1
    entry = profile["tdee_history"][-1]
    assert entry["event"] == "body_profile_change"
    assert int(entry["before"]) == 2759
    assert int(entry["after"]) == new_baseline


@pytest.mark.usefixtures("ssm_params")
def test_no_body_profile_change_does_not_touch_tdee(dynamodb_table: Any) -> None:
    """Same body_profile values + manual kcal/macros override → tdee unchanged."""
    from handlers.profile_targets.schemas import BodyProfile
    from handlers.profile_targets.service import update_targets

    _seed_profile(
        dynamodb_table,
        "tomek",
        height_cm=180,
        age=30,
        sex="male",
        activity_level="moderate",
        goal="maintain",
        tdee_baseline=2759,
        tdee_adaptive=2900,
    )
    _seed_weight(dynamodb_table, "tomek", day=date.today().isoformat(), kg=80.0)

    # Same body_profile values
    bp = BodyProfile(
        height_cm=180,
        age=30,
        sex="male",
        activity_level="moderate",
        goal="maintain",
    )
    update_targets("tomek", 2500, 150, 80, 250, body_profile=bp)

    profile = dynamodb_table.get_item(Key={"PK": "USER#tomek", "SK": "PROFILE"})["Item"]
    assert int(profile["tdee_baseline"]) == 2759  # unchanged
    assert int(profile["tdee_adaptive"]) == 2900  # unchanged (NIE reset)
    assert int(profile["kcal_target"]) == 2500  # manual override preserved
    assert int(profile["protein_target_g"]) == 150
    assert "tdee_history" not in profile  # nigdy nie touchowano


@pytest.mark.usefixtures("ssm_params")
def test_history_cap_20_fifo_in_update_targets(dynamodb_table: Any) -> None:
    """20 history entries istnieje → body_profile_change → drop oldest, append new = nadal 20."""
    from handlers.profile_targets.schemas import BodyProfile
    from handlers.profile_targets.service import update_targets

    existing = [
        {
            "date": f"2026-04-{i:02d}",
            "event": "recalc",
            "before": 2759,
            "after": 2759,
            "kcal_in_avg": 2080,
            "waga_delta_kg": Decimal("0"),
            "adjustment": 0,
            "capped": False,
            "reason": None,
        }
        for i in range(1, 21)
    ]
    _seed_profile(
        dynamodb_table,
        "tomek",
        height_cm=180,
        age=30,
        sex="male",
        activity_level="moderate",
        goal="maintain",
        tdee_baseline=2759,
        tdee_adaptive=2759,
        tdee_history=existing,
    )
    _seed_weight(dynamodb_table, "tomek", day=date.today().isoformat(), kg=80.0)

    bp = BodyProfile(
        height_cm=180,
        age=30,
        sex="male",
        activity_level="heavy",  # zmienione → trigger reset
        goal="maintain",
    )
    update_targets("tomek", 2900, 145, 70, 395, body_profile=bp)

    profile = dynamodb_table.get_item(Key={"PK": "USER#tomek", "SK": "PROFILE"})["Item"]
    assert len(profile["tdee_history"]) == 20
    assert profile["tdee_history"][-1]["event"] == "body_profile_change"
    # Oldest (2026-04-01) dropped
    assert all(e["date"] != "2026-04-01" for e in profile["tdee_history"])


@pytest.mark.usefixtures("ssm_params")
def test_body_profile_change_without_weight_keeps_user_provided_values(
    dynamodb_table: Any,
) -> None:
    """Brak waga w BIOMETRY + body_profile initial save → no TDEE init, manual values preserved."""
    from handlers.profile_targets.schemas import BodyProfile
    from handlers.profile_targets.service import update_targets

    _seed_profile(dynamodb_table, "tomek")
    # NO weight seeded

    bp = BodyProfile(
        height_cm=180,
        age=30,
        sex="male",
        activity_level="moderate",
        goal="maintain",
    )
    update_targets("tomek", 2000, 130, 70, 200, body_profile=bp)

    profile = dynamodb_table.get_item(Key={"PK": "USER#tomek", "SK": "PROFILE"})["Item"]
    # No TDEE init (waga brak)
    assert "tdee_baseline" not in profile
    assert "tdee_adaptive" not in profile
    # Manual values preserved
    assert int(profile["kcal_target"]) == 2000
    assert int(profile["protein_target_g"]) == 130
    # Body profile saved (5 fields)
    assert int(profile["height_cm"]) == 180
    assert profile["activity_level"] == "moderate"
