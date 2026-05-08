"""Unit tests dla `handlers.advisor_chat.service` (Sprint 6.1 PR1).

Skupiamy się na deterministycznych unit testach service-layer logiki bez
Lambda event mock. Handler-level scenariusze są w `test_handler.py`.

Pokrycie:
- `read_history` — chronological order, empty case
- `append_message` — monotonic turn_idx, TTL correctness, race-safe retry,
  passed-history short-circuit (no duplicate Query)
- `build_chat_messages` — composed message shape (3 bloki, no retrieved_recipes)
- `call_chat` — cache_control marker present (PR1 invariant)
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

WARSAW_TZ = ZoneInfo("Europe/Warsaw")


# ─── read_history ─────────────────────────────────────────────────────────


def test_read_history_chronologic_order(
    dynamodb_table_with_chat_history: Any,
) -> None:
    """Pre-seeded 5 turn (idx 0..4) → `read_history` zwraca list w order po
    `turn_idx` (DDB Query w SK ascending)."""
    from handlers.advisor_chat.service import read_history

    today = datetime.now(WARSAW_TZ).date()
    history = read_history("user_a", today)

    assert [m.turn_idx for m in history] == [0, 1, 2, 3, 4]
    assert [m.role for m in history] == [
        "user",
        "assistant",
        "user",
        "assistant",
        "user",
    ]
    assert history[0].content == "Co zjeść na obiad?"
    assert history[4].content == "Ile białka w tym?"


def test_read_history_empty(dynamodb_table: Any) -> None:
    """Brak rows dla today → `[]`."""
    from handlers.advisor_chat.service import read_history

    today = datetime.now(WARSAW_TZ).date()
    history = read_history("ghost_user", today)
    assert history == []


# ─── append_message ──────────────────────────────────────────────────────


def test_append_message_monotonic_turn_idx(dynamodb_table: Any) -> None:
    """3× `append_message` → DDB ma turn_idx 0, 1, 2 + zero-padded SK."""
    from handlers.advisor_chat.service import append_message, read_history

    today = datetime.now(WARSAW_TZ).date()

    idx0 = append_message("alice", today, "user", "msg 1")
    idx1 = append_message("alice", today, "assistant", "reply 1")
    idx2 = append_message("alice", today, "user", "msg 2")

    assert idx0 == 0
    assert idx1 == 1
    assert idx2 == 2

    history = read_history("alice", today)
    assert [m.turn_idx for m in history] == [0, 1, 2]

    # Verify SK shape (zero-padded 4-cyfry).
    raw = dynamodb_table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
        ExpressionAttributeValues={
            ":pk": "USER#alice",
            ":sk": f"CHAT#{today.isoformat()}#",
        },
    )
    sks = sorted(item["SK"] for item in raw["Items"])
    assert sks == [
        f"CHAT#{today.isoformat()}#0000",
        f"CHAT#{today.isoformat()}#0001",
        f"CHAT#{today.isoformat()}#0002",
    ]


def test_append_message_ttl_correct(dynamodb_table: Any) -> None:
    """TTL = epoch_now + 86400 (24h rolling window per ADR-007 D6)."""
    from handlers.advisor_chat.service import append_message

    today = datetime.now(WARSAW_TZ).date()
    before = int(time.time())
    append_message("alice", today, "user", "ping")
    after = int(time.time())

    raw = dynamodb_table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
        ExpressionAttributeValues={
            ":pk": "USER#alice",
            ":sk": f"CHAT#{today.isoformat()}#",
        },
    )
    items = raw["Items"]
    assert len(items) == 1
    ttl = int(items[0]["ttl"])
    # 5s tolerance dla naprawdę wolnego CI
    assert before + 86400 <= ttl <= after + 86400 + 5


# ─── append_message — race-safety / passed history ───────────────────────


def test_append_message_collision_retries(dynamodb_table: Any) -> None:
    """Pre-write `CHAT#{today}#0000` direct → caller passes empty history,
    `append_message` myśli `next_idx=0`, conditional PutItem failuje, retry
    z fresh DDB read → wybiera `next_idx=1`. Returns 1.

    Symuluje TOCTOU race: dwa concurrent requests w oknie ~3-5s Anthropic
    call wyliczyły ten sam `next_idx`; drugi przegrywa kolizję, retryuje.
    """
    from handlers.advisor_chat.service import append_message

    today = datetime.now(WARSAW_TZ).date()
    today_iso = today.isoformat()

    # Inny "request" zapisał już idx=0 zanim tutaj retryujemy.
    dynamodb_table.put_item(
        Item={
            "PK": "USER#alice",
            "SK": f"CHAT#{today_iso}#0000",
            "role": "user",
            "content": "first writer wins",
            "ts": f"{today_iso}T12:00:00+00:00",
            "ttl": int(time.time()) + 86400,
        }
    )

    # Caller pomyłkowo przekazuje pustą historię (snapshot stale) → próba
    # idx=0 → kolizja → retry z None → re-read DDB → idx=1.
    assigned = append_message("alice", today, "user", "second writer", history=[])
    assert assigned == 1

    raw = dynamodb_table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :sk)",
        ExpressionAttributeValues={
            ":pk": "USER#alice",
            ":sk": f"CHAT#{today_iso}#",
        },
    )
    sks = sorted(item["SK"] for item in raw["Items"])
    assert sks == [
        f"CHAT#{today_iso}#0000",
        f"CHAT#{today_iso}#0001",
    ]


def test_append_message_exhausted_retries_raises(
    dynamodb_table: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`put_item_idempotent` zawsze False → po `MAX_APPEND_RETRIES` próbach
    `AdvisorBackendError("turn_idx_collision_after_retries")`."""
    from handlers.advisor_chat import service as svc

    today = datetime.now(WARSAW_TZ).date()
    call_count = {"n": 0}

    def _always_fails(pk: str, sk: str, attrs: dict[str, Any]) -> bool:
        call_count["n"] += 1
        return False

    monkeypatch.setattr(svc, "put_item_idempotent", _always_fails)

    with pytest.raises(svc.AdvisorBackendError, match="turn_idx_collision_after_retries"):
        svc.append_message("alice", today, "user", "x", history=[])

    assert call_count["n"] == svc.MAX_APPEND_RETRIES


def test_append_message_uses_passed_history_no_duplicate_query(
    dynamodb_table: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Caller przekazuje `history=[ChatMessage(...)]` → `append_message` NIE
    woła `read_history` (pierwsza próba używa snapshota; tylko collision-retry
    re-readuje)."""
    from handlers.advisor_chat import service as svc
    from handlers.advisor_chat.schemas import ChatMessage

    today = datetime.now(WARSAW_TZ).date()
    read_calls = {"n": 0}
    real_read_history = svc.read_history

    def _spy(user_id: str, today: Any) -> Any:
        read_calls["n"] += 1
        return real_read_history(user_id, today)

    monkeypatch.setattr(svc, "read_history", _spy)

    history = [
        ChatMessage(
            role="user",
            content="prev",
            turn_idx=3,
            ts=f"{today.isoformat()}T11:00:00+00:00",
        ),
    ]
    assigned = svc.append_message("alice", today, "user", "next", history=history)

    # next_idx = max(3) + 1 = 4
    assert assigned == 4
    # Kluczowe: NO duplicate Query.
    assert read_calls["n"] == 0


# ─── build_chat_messages ──────────────────────────────────────────────────


def _make_today_state() -> Any:
    """Helper — minimal valid TodayState dla unit testów composition."""
    from handlers.advisor_chat.schemas import TodayState

    return TodayState(
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


def test_build_chat_messages_no_retrieved_recipes() -> None:
    """PR1 invariant — composed message NIE zawiera `<retrieved_recipes>`.

    PR2 doda RAG retrieval block; w PR1 pilnujemy nieobecności.
    """
    from handlers.advisor_chat.service import build_chat_messages

    state = _make_today_state()
    messages = build_chat_messages([], state, "Cześć!")
    composed = messages[0]["content"]
    assert "<retrieved_recipes>" not in composed
    assert "</retrieved_recipes>" not in composed


def test_build_chat_messages_includes_three_blocks() -> None:
    """Composed message ZAWIERA `<conversation_history>`, `<today_context>`,
    `<user_message>` — 3 wymagane bloki PR1."""
    from handlers.advisor_chat.schemas import ChatMessage
    from handlers.advisor_chat.service import build_chat_messages

    state = _make_today_state()
    history = [
        ChatMessage(role="user", content="hi", turn_idx=0, ts="2026-05-07T10:00:00+00:00"),
        ChatMessage(
            role="assistant",
            content="cześć",
            turn_idx=1,
            ts="2026-05-07T10:00:01+00:00",
        ),
    ]
    messages = build_chat_messages(history, state, "kolejne pytanie")
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    composed = messages[0]["content"]
    assert "<conversation_history>" in composed
    assert "</conversation_history>" in composed
    assert "<today_context>" in composed
    assert "</today_context>" in composed
    assert "<user_message>" in composed
    assert "</user_message>" in composed
    # Format historii: "turn N [role]: content"
    assert "turn 0 [user]: hi" in composed
    assert "turn 1 [assistant]: cześć" in composed
    # Today state JSON faktycznie wstrzyknięty
    assert "kcal_target" in composed
    # User message wstawiony
    assert "kolejne pytanie" in composed


# ─── call_chat (Anthropic) ────────────────────────────────────────────────


@pytest.mark.usefixtures("ssm_with_anthropic_key")
def test_anthropic_cache_marker_present(
    dynamodb_table: Any, patched_anthropic_client: MagicMock
) -> None:
    """`call_chat` musi wysłać system prompt z `cache_control: ephemeral` —
    inaczej Anthropic prompt caching się nie załączy (5min TTL)."""
    from handlers.advisor_chat.service import call_chat

    text, tokens = call_chat("SYSTEM TEXT", [{"role": "user", "content": "x"}])

    assert isinstance(text, str)
    assert tokens.input_tokens == 100  # default mock
    assert tokens.output_tokens == 50

    create_call = patched_anthropic_client.messages.create.call_args
    system_blocks = create_call.kwargs["system"]
    assert isinstance(system_blocks, list)
    assert len(system_blocks) == 1
    block = system_blocks[0]
    assert block["type"] == "text"
    assert block["text"] == "SYSTEM TEXT"
    assert block["cache_control"] == {"type": "ephemeral"}
