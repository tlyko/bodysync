"""Unit tests dla advisor_dinner.service helpery (build_today_state +
get_anthropic_client guard + cache shape).

Handler-level scenariusze są w test_handler.py — tu skupiamy się na
deterministycznych unit testach service-layer logiki bez Lambda event mock.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import boto3
import pytest


@pytest.mark.usefixtures("dynamodb_table")
def test_get_anthropic_client_raises_when_placeholder() -> None:
    """SSM zwraca PLACEHOLDER → AdvisorUnavailableError. Defense-in-depth
    przeciw fail-open gdy owner nie wpisał real key po terraform apply.
    """
    from handlers.advisor_dinner.service import (
        AdvisorUnavailableError,
        _reset_client_for_tests,
        get_anthropic_client,
    )
    from shared import ssm as _ssm

    boto3.client("ssm", region_name="eu-west-1").put_parameter(
        Name="/bodysync/anthropic/api_key",
        Value="PLACEHOLDER",
        Type="SecureString",
    )
    _ssm.clear_cache()
    _reset_client_for_tests()

    with pytest.raises(AdvisorUnavailableError):
        get_anthropic_client()


@pytest.mark.usefixtures("dynamodb_table")
def test_get_anthropic_client_raises_when_key_too_short() -> None:
    """Key krótszy niż 50 chars → AdvisorUnavailableError. Reject typowych
    błędów copy-paste (np. wklejenie tylko prefix).
    """
    from handlers.advisor_dinner.service import (
        AdvisorUnavailableError,
        _reset_client_for_tests,
        get_anthropic_client,
    )
    from shared import ssm as _ssm

    boto3.client("ssm", region_name="eu-west-1").put_parameter(
        Name="/bodysync/anthropic/api_key",
        Value="sk-ant-tooshort",  # 15 chars
        Type="SecureString",
    )
    _ssm.clear_cache()
    _reset_client_for_tests()

    with pytest.raises(AdvisorUnavailableError):
        get_anthropic_client()


def test_build_user_message_wraps_notes_in_user_note_block() -> None:
    """build_user_message produkuje deterministic shape:
    <context>...</context> + opcjonalny <user_note>...</user_note>.
    """
    from handlers.advisor_dinner.schemas import TodayState
    from handlers.advisor_dinner.service import build_user_message

    state = TodayState(
        kcal_consumed=1500.0,
        kcal_active=400.0,
        kcal_basal=1700.0,
        kcal_target=1800,
        kcal_remaining=300.0,
        protein_consumed_g=80.0,
        protein_target_g=130,
        fat_target_g=70,
        carbs_target_g=200,
        step_count=8000,
    )
    msg = build_user_message(state, "lekka kolacja proszę")
    assert "<context>" in msg
    assert "</context>" in msg
    assert "<user_note>" in msg
    assert "lekka kolacja proszę" in msg
    assert "</user_note>" in msg
    assert "Zaproponuj 3 propozycje kolacji" in msg


def test_build_user_message_no_notes_omits_user_note_block() -> None:
    """Bez notes message NIE zawiera <user_note> bloku."""
    from handlers.advisor_dinner.schemas import TodayState
    from handlers.advisor_dinner.service import build_user_message

    state = TodayState(
        kcal_consumed=0.0,
        kcal_active=0.0,
        kcal_basal=0.0,
        kcal_target=2000,
        kcal_remaining=2000.0,
        protein_consumed_g=0.0,
        protein_target_g=130,
        fat_target_g=70,
        carbs_target_g=200,
        step_count=0,
    )
    msg = build_user_message(state, None)
    assert "<context>" in msg
    assert "<user_note>" not in msg
    assert "</user_note>" not in msg


@pytest.mark.usefixtures("ssm_params")
def test_build_today_state_with_empty_ddb_returns_zeros(dynamodb_table: Any) -> None:
    """User bez żadnych BIOMETRY rows + bez PROFILE → wszystko zeroed
    (defaults z PROFILE fallback)."""
    from handlers.advisor_dinner.service import build_today_state

    today = datetime.now(UTC).date()
    state = build_today_state("ghost", today)
    assert state.kcal_consumed == 0.0
    assert state.kcal_active == 0.0
    assert state.kcal_basal == 0.0
    assert state.protein_consumed_g == 0.0
    assert state.step_count == 0
    assert state.kcal_target == 2000
    assert state.protein_target_g == 130
    assert state.weight_kg_today is None
    assert state.weight_kg_7d_avg is None
    assert state.sleep_hours_last_night is None
    assert state.hrv_sdnn_24h_avg is None


@pytest.mark.usefixtures("ssm_params")
def test_build_today_state_aggregates_cumulative_buckets(dynamodb_table: Any) -> None:
    """3 kcal_in buckety + 2 protein buckety → suma w state."""
    from handlers.advisor_dinner.service import build_today_state

    today = datetime.now(UTC).date()
    today_iso = today.isoformat()
    pk = "USER#alice"
    for hour, qty in [("08:00", "300"), ("13:00", "550"), ("18:00", "400")]:
        dynamodb_table.put_item(
            Item={
                "PK": pk,
                "SK": f"BIOMETRY#{today_iso}#kcal_in#{today_iso}T{hour}:00+00:00",
                "kcal": Decimal(qty),
            }
        )
    for hour, qty in [("13:00", "30"), ("18:00", "40")]:
        dynamodb_table.put_item(
            Item={
                "PK": pk,
                "SK": f"BIOMETRY#{today_iso}#protein#{today_iso}T{hour}:00+00:00",
                "g": Decimal(qty),
            }
        )

    state = build_today_state("alice", today)
    assert state.kcal_consumed == 1250.0
    assert state.protein_consumed_g == 70.0


@pytest.mark.usefixtures("ssm_params")
def test_build_today_state_weight_7d_avg(dynamodb_table: Any) -> None:
    """Weight snapshots z 7d → weight_kg_7d_avg = średnia.

    Kicker: weight to snapshot (3-part SK), nie multipoint — `_query_snapshots_in_range`.
    """
    from handlers.advisor_dinner.service import build_today_state

    today = datetime.now(UTC).date()
    pk = "USER#alice"
    # 3 dni weight (today, today-3, today-6)
    for offset, kg in [(0, "78.0"), (3, "78.5"), (6, "79.0")]:
        d = (today - timedelta(days=offset)).isoformat()
        dynamodb_table.put_item(Item={"PK": pk, "SK": f"BIOMETRY#{d}#weight", "kg": Decimal(kg)})
    state = build_today_state("alice", today)
    assert state.weight_kg_today == 78.0
    # avg(78.0, 78.5, 79.0) = 78.5
    assert state.weight_kg_7d_avg == 78.5


@pytest.mark.usefixtures("ssm_params")
def test_build_today_state_pk_isolation(dynamodb_table: Any) -> None:
    """Bob's BIOMETRY nie wlicza się do alice'a state."""
    from handlers.advisor_dinner.service import build_today_state

    today = datetime.now(UTC).date().isoformat()
    today_obj = datetime.now(UTC).date()
    # Bob's data — alice nie powinien widzieć
    dynamodb_table.put_item(
        Item={
            "PK": "USER#bob",
            "SK": f"BIOMETRY#{today}#kcal_in#{today}T13:00:00+00:00",
            "kcal": Decimal("5000"),
        }
    )
    state = build_today_state("alice", today_obj)
    assert state.kcal_consumed == 0.0
