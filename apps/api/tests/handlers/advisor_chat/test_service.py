"""Unit tests dla `handlers.advisor_chat.service` (Sprint 6.1 PR1).

Skupiamy się na deterministycznych unit testach service-layer logiki bez
Lambda event mock. Handler-level scenariusze są w `test_handler.py`.

Pokrycie:
- `read_history` — chronological order, empty case
- `append_message` — monotonic turn_idx, TTL correctness, race-safe retry,
  passed-history short-circuit (no duplicate Query)
- `build_chat_messages` — composed message shape (3-4 bloki, retrieved cache marker)
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


# ─── is_food_related ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "message",
    [
        "Co zjeść na śniadanie?",
        "Daj mi przepis na obiad",
        "Ile kalorii dziennie żeby schudnąć?",
        "Jaki shake po treningu",
        "Potrzebuję więcej białka",
        "Deficyt 500 kcal — jak ułożyć posiłki?",
        "Owsianka z bananem — ok przed treningiem?",
        "Co kupić w Lidlu na tydzień?",
        "Makro na masie",
        "Zjadłem tylko 1500 kcal — mało?",
    ],
)
def test_is_food_related_true_for_food_queries(message: str) -> None:
    from handlers.advisor_chat.service import is_food_related

    assert is_food_related(message) is True, f"expected True dla: {message!r}"


@pytest.mark.parametrize(
    "message",
    [
        "Ile dziś ważę?",
        "Jaki mam dziś trening?",
        "Powinienem dziś pójść biegać?",
        "Co z moim HRV ostatnio?",
        "Czy mam się dziś zregenerować?",
        "Czy iść na siłownię z bólem kolana?",
        "Ile spałem w nocy?",
        "",
        "   ",
    ],
)
def test_is_food_related_false_for_non_food_queries(message: str) -> None:
    from handlers.advisor_chat.service import is_food_related

    assert is_food_related(message) is False, f"expected False dla: {message!r}"


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


def _flatten_blocks(content: Any) -> str:
    """Helper — concat wszystkich text blocks w composed user message.

    Po Sprint 6.2 PR2 Step 4 `build_chat_messages` zwraca multi-block
    content array (dla per-block `cache_control` markera na retrieved).
    Tests które patrzą na "czy literal jest w composed" robią flatten.
    """
    if isinstance(content, str):
        return content
    return "".join(b["text"] for b in content if b.get("type") == "text")


def test_build_chat_messages_no_retrieved_recipes() -> None:
    """Brak `retrieved_recipes` (default None) ⇒ composed message NIE
    zawiera `<retrieved_recipes>` block. Graceful degradation gdy RAG fail.
    """
    from handlers.advisor_chat.service import build_chat_messages

    state = _make_today_state()
    messages = build_chat_messages([], state, "Cześć!")
    composed = _flatten_blocks(messages[0]["content"])
    assert "<retrieved_recipes>" not in composed
    assert "</retrieved_recipes>" not in composed
    # Default None lub [] ⇒ 2 bloki (base + user_message), żaden nie ma
    # cache_control marker (cache markowany jest tylko retrieved block).
    blocks = messages[0]["content"]
    assert isinstance(blocks, list)
    assert len(blocks) == 2
    assert all("cache_control" not in b for b in blocks)


def test_build_chat_messages_includes_three_blocks() -> None:
    """Composed message ZAWIERA `<conversation_history>`, `<today_context>`,
    `<user_message>` — 3 wymagane bloki w content array."""
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
    composed = _flatten_blocks(messages[0]["content"])
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


def test_build_chat_messages_with_retrieved_recipes() -> None:
    """Sprint 6.2 PR2 — `retrieved_recipes` truthy ⇒ dodatkowy content block
    z `<retrieved_recipes>` JSON + `cache_control: ephemeral` marker.

    Per ADR-007 D6 cache hierarchy — drugi cache marker (osobny od system
    prompt) opłaca się dla top-K stable across podobnych queries.
    """
    from handlers.advisor_chat.schemas import UsedRecipe
    from handlers.advisor_chat.service import build_chat_messages

    state = _make_today_state()
    recipes = [
        UsedRecipe(slug="kurczak-z-ryżem", name="Kurczak z ryżem", kcal=540, similarity_score=0.82),
        UsedRecipe(slug="łosoś-pieczony", name="Łosoś pieczony", kcal=620, similarity_score=0.79),
    ]
    messages = build_chat_messages([], state, "co zjeść", retrieved_recipes=recipes)

    blocks = messages[0]["content"]
    assert isinstance(blocks, list)
    assert len(blocks) == 3  # base + retrieved + user_message

    composed = _flatten_blocks(blocks)
    assert "<retrieved_recipes>" in composed
    assert "</retrieved_recipes>" in composed
    # Slug + name + kcal trafiają do JSON
    assert "kurczak-z-ryżem" in composed
    assert "Łosoś pieczony" in composed
    assert "540" in composed

    # Cache marker — TYLKO na retrieved block (block index 1).
    cache_blocks = [b for b in blocks if b.get("cache_control") == {"type": "ephemeral"}]
    assert len(cache_blocks) == 1
    assert "<retrieved_recipes>" in cache_blocks[0]["text"]


def test_build_chat_messages_empty_retrieved_skipped() -> None:
    """`retrieved_recipes=[]` traktowane jak None — block pominięty
    (graceful degradation gdy retrieve zwrócił 0 wyników)."""
    from handlers.advisor_chat.service import build_chat_messages

    state = _make_today_state()
    messages = build_chat_messages([], state, "halo", retrieved_recipes=[])
    composed = _flatten_blocks(messages[0]["content"])
    assert "<retrieved_recipes>" not in composed
    blocks = messages[0]["content"]
    assert len(blocks) == 2  # base + user_message; brak retrieved block


# ─── load_recent_activities ───────────────────────────────────────────────


def _put_activity(
    dynamodb_table: Any,
    *,
    user_id: str = "user_a",
    strava_id: int,
    start_date: str,
    sport_type: str = "Run",
    name: str | None = None,
    distance_m: float | None = None,
    moving_time_s: int | None = None,
    average_heartrate: float | None = None,
    max_heartrate: float | None = None,
    calories: float | None = None,
) -> None:
    """Helper — seed ACTIVITY row z minimal required fields."""
    item: dict[str, Any] = {
        "PK": f"USER#{user_id}",
        "SK": f"ACTIVITY#{strava_id}",
        "strava_id": strava_id,
        "start_date": start_date,
        "sport_type": sport_type,
    }
    if name is not None:
        item["name"] = name
    if distance_m is not None:
        item["distance_m"] = distance_m
    if moving_time_s is not None:
        item["moving_time_s"] = moving_time_s
    if average_heartrate is not None:
        item["average_heartrate"] = average_heartrate
    if max_heartrate is not None:
        item["max_heartrate"] = max_heartrate
    if calories is not None:
        item["calories"] = calories
    dynamodb_table.put_item(Item=item)


def test_load_recent_activities_filters_to_window(dynamodb_table: Any) -> None:
    """7d window: rows ze `start_date < today-6d` są odrzucone."""
    from datetime import timedelta

    from handlers.advisor_chat.service import load_recent_activities

    today = datetime.now(WARSAW_TZ).date()
    inside_a = today - timedelta(days=2)
    inside_b = today - timedelta(days=6)
    outside = today - timedelta(days=10)

    _put_activity(dynamodb_table, strava_id=1, start_date=f"{inside_a}T07:00:00Z")
    _put_activity(dynamodb_table, strava_id=2, start_date=f"{inside_b}T07:00:00Z")
    _put_activity(dynamodb_table, strava_id=3, start_date=f"{outside}T07:00:00Z")

    result = load_recent_activities("user_a", today=today)

    assert len(result) == 2
    assert {a.date for a in result} == {inside_a.isoformat(), inside_b.isoformat()}


def test_load_recent_activities_sorted_desc_by_date(dynamodb_table: Any) -> None:
    """Najnowsze pierwsze (LLM oczekuje recent na górze)."""
    from datetime import timedelta

    from handlers.advisor_chat.service import load_recent_activities

    today = datetime.now(WARSAW_TZ).date()
    _put_activity(dynamodb_table, strava_id=1, start_date=f"{today - timedelta(days=5)}T07:00:00Z")
    _put_activity(dynamodb_table, strava_id=2, start_date=f"{today - timedelta(days=1)}T07:00:00Z")
    _put_activity(dynamodb_table, strava_id=3, start_date=f"{today - timedelta(days=3)}T07:00:00Z")

    result = load_recent_activities("user_a", today=today)
    dates = [a.date for a in result]
    assert dates == sorted(dates, reverse=True)


def test_load_recent_activities_caps_at_max(dynamodb_table: Any) -> None:
    """Aktywny tydzień (>15 treningów) → cap RECENT_ACTIVITIES_MAX."""
    from datetime import timedelta

    from handlers.advisor_chat.service import RECENT_ACTIVITIES_MAX, load_recent_activities

    today = datetime.now(WARSAW_TZ).date()
    # 20 aktywności w 7d window — 2-3 per dzień (np. siłka + bieg + spacer).
    for i in range(20):
        day_offset = i % 7  # rozłóż na 7 dni
        _put_activity(
            dynamodb_table,
            strava_id=1000 + i,
            start_date=f"{today - timedelta(days=day_offset)}T{(7 + i % 12):02d}:00:00Z",
        )

    result = load_recent_activities("user_a", today=today)
    assert len(result) == RECENT_ACTIVITIES_MAX


def test_load_recent_activities_empty_when_no_rows(dynamodb_table: Any) -> None:
    """Brak ACTIVITY rows → [], advisor pomija block w prompt."""
    from handlers.advisor_chat.service import load_recent_activities

    today = datetime.now(WARSAW_TZ).date()
    result = load_recent_activities("ghost_user", today=today)
    assert result == []


def test_load_recent_activities_decimal_conversion(dynamodb_table: Any) -> None:
    """DDB zwraca `Decimal` dla numerycznych pól → Pydantic potrzebuje float/int.
    Sprawdzamy że konwersja distance/HR/kcal działa bez crash."""
    from decimal import Decimal

    from handlers.advisor_chat.service import load_recent_activities

    today = datetime.now(WARSAW_TZ).date()
    # Boto3 DDB zwraca numbers jako Decimal; symulujemy bezpośrednio.
    dynamodb_table.put_item(
        Item={
            "PK": "USER#user_a",
            "SK": "ACTIVITY#42",
            "strava_id": 42,
            "start_date": f"{today.isoformat()}T07:00:00Z",
            "sport_type": "Run",
            "name": "Poranny bieg",
            "distance_m": Decimal("8234.5"),
            "moving_time_s": Decimal("2700"),
            "average_heartrate": Decimal("152.4"),
            "max_heartrate": Decimal("178"),
            "calories": Decimal("581.2"),
        }
    )

    result = load_recent_activities("user_a", today=today)
    assert len(result) == 1
    a = result[0]
    assert a.sport_type == "Run"
    assert a.name == "Poranny bieg"
    assert a.distance_km == 8.23
    assert a.duration_min == 45
    assert a.avg_hr == 152
    assert a.max_hr == 178
    assert a.kcal == 581


def test_load_recent_activities_truncates_long_name(dynamodb_table: Any) -> None:
    """Strava name max ~256 chars; truncate do RECENT_ACTIVITIES_NAME_MAX_LEN
    chroni przed token bombs."""
    from handlers.advisor_chat.service import (
        RECENT_ACTIVITIES_NAME_MAX_LEN,
        load_recent_activities,
    )

    today = datetime.now(WARSAW_TZ).date()
    long_name = "X" * 500
    _put_activity(
        dynamodb_table,
        strava_id=1,
        start_date=f"{today.isoformat()}T07:00:00Z",
        name=long_name,
    )

    result = load_recent_activities("user_a", today=today)
    assert len(result) == 1
    assert result[0].name is not None
    assert len(result[0].name) == RECENT_ACTIVITIES_NAME_MAX_LEN


def test_load_recent_activities_pk_isolation(dynamodb_table: Any) -> None:
    """user_a query NIE zwraca ACTIVITY rows user_b (CLAUDE.md PK isolation)."""
    from handlers.advisor_chat.service import load_recent_activities

    today = datetime.now(WARSAW_TZ).date()
    _put_activity(
        dynamodb_table,
        user_id="user_b",
        strava_id=99,
        start_date=f"{today.isoformat()}T07:00:00Z",
    )

    result = load_recent_activities("user_a", today=today)
    assert result == []


# ─── build_chat_messages with recent_activities ───────────────────────────


def test_build_chat_messages_with_recent_activities() -> None:
    """recent_activities truthy ⇒ dodatkowy block `<recent_activities>`
    z cache_control marker + 1-liniowy format per activity."""
    from handlers.advisor_chat.schemas import RecentActivity
    from handlers.advisor_chat.service import build_chat_messages

    state = _make_today_state()
    activities = [
        RecentActivity(
            date="2026-05-09",
            sport_type="Run",
            name="Poranny bieg",
            distance_km=8.2,
            duration_min=45,
            avg_hr=152,
            max_hr=175,
            kcal=580,
        ),
        RecentActivity(
            date="2026-05-08",
            sport_type="Walk",
            distance_km=3.5,
            duration_min=50,
        ),
    ]
    messages = build_chat_messages([], state, "co o moim biegu", recent_activities=activities)

    blocks = messages[0]["content"]
    assert isinstance(blocks, list)
    composed = _flatten_blocks(blocks)
    assert "<recent_activities>" in composed
    assert "</recent_activities>" in composed
    assert "Run" in composed
    assert "Poranny bieg" in composed
    assert "8.2km" in composed
    assert "HR avg 152/max 175" in composed
    assert "580 kcal" in composed
    # Activity z brak HR/kcal — nie powinno mieć tych pól
    assert "Walk" in composed
    assert "3.5km" in composed

    # Cache marker — recent_activities block musi być oddzielnie cached.
    cache_blocks = [b for b in blocks if b.get("cache_control") == {"type": "ephemeral"}]
    activities_cache = [b for b in cache_blocks if "<recent_activities>" in b["text"]]
    assert len(activities_cache) == 1


def test_build_chat_messages_empty_activities_skipped() -> None:
    """recent_activities=[] traktowane jak None — block pominięty."""
    from handlers.advisor_chat.service import build_chat_messages

    state = _make_today_state()
    messages = build_chat_messages([], state, "halo", recent_activities=[])
    composed = _flatten_blocks(messages[0]["content"])
    assert "<recent_activities>" not in composed


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


def test_system_prompt_meets_haiku_cache_minimum() -> None:
    """Regression — system_prompt.txt musi mieć >= 14000 chars (~4500 PL
    tokens) żeby Anthropic prompt cache działał dla Haiku 4.5.

    Per docs.anthropic.com/.../prompt-caching minimum tokens dla cache
    marker:
      - Haiku 4.5: 4096
      - Sonnet 4.6: 2048
      - Sonnet 4.5: 1024

    Polska gęstość ~3.5 chars/token, więc 14000 chars ≈ 4000 tokens
    z marginesem do 4096. Nie skracaj poniżej tej wartości — Anthropic
    silently odrzuca cache marker i każdy call jest billed full input
    tokens (~10x drożej niż cached read).
    """
    from pathlib import Path

    prompt_path = (
        Path(__file__).resolve().parents[3] / "handlers" / "advisor_chat" / "system_prompt.txt"
    )
    content = prompt_path.read_text(encoding="utf-8")
    assert len(content) >= 14000, (
        f"system_prompt.txt={len(content)} chars; needs >=14000 (~4500 PL "
        f"tokens) dla Haiku 4.5 cache marker minimum (4096 tokens)"
    )
