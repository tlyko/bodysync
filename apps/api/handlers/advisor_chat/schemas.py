"""Pydantic schemas dla `POST /api/advisor/chat` (Sprint 6.1 PR1 per ADR-007).

Request: `message` (1-2000 chars). User_id z JWT cookie, brak field w body —
defense przeciw IDOR.

Response: `content` (assistant reply), `used_recipes` (PR1 placeholder, PR2
fills via RAG), `turn_idx`, `tokens_used`, `generated_at`. `today_state`
snapshot wstrzykiwany w prompt jako `<today_context>` (patrz `system_prompt.txt`).

DDB chat history row layout (per ADR-007 D6):
    PK = USER#{user_id}
    SK = CHAT#{date}#{turn_idx:04d}    # date = YYYY-MM-DD UTC
    attrs = {role, content, ts, ttl, tokens_used (optional, assistant only)}
    ttl = epoch_now + 86400              # 24h rolling window
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Body dla `POST /api/advisor/chat`.

    `message` to user turn — wrap w `<user_message>` z prompt-injection guard
    w system promp (patrz `system_prompt.txt`). Max 2000 chars — wystarczy
    na realistyczne pytanie, blokuje payload bombs.
    """

    message: str = Field(..., min_length=1, max_length=2000)


class TodayState(BaseModel):
    """Snapshot dzisiejszych metryk widziany przez LLM. Frontend renderuje
    jako collapsible debug, LLM używa do uzasadnienia odpowiedzi.

    Cumulative pola (kcal_*, protein/fat/carbs, steps) — sumy z hourly
    bucketów `BIOMETRY#{today}#{metric}#{ts}` agregowane przez
    `sum_metric_today`. Snapshoty (weight, sleep, hrv, resting_hr) — single
    item per dzień, czytane przez `query_by_pk` + parse.

    Floats zaokrąglane do 1 miejsca przed wstawieniem (UI prefer simple
    integery, LLM też nie potrzebuje precyzji 5 miejsc po przecinku).
    """

    kcal_consumed: float
    kcal_active: float
    kcal_basal: float
    kcal_target: int
    kcal_remaining: float
    protein_consumed_g: float
    protein_target_g: int
    fat_target_g: int
    carbs_target_g: int
    step_count: int
    weight_kg_today: float | None = None
    weight_kg_7d_avg: float | None = None
    sleep_hours_last_night: float | None = None
    hrv_sdnn_24h_avg: float | None = None
    resting_hr_7d_avg: float | None = None


class ChatMessage(BaseModel):
    """DDB chat history row (per ADR-007 D6).

    Reprezentuje pojedynczą turę w historii rozmowy. `turn_idx` rośnie
    monotonicznie w obrębie dnia (0, 1, 2, ...) — używane do sortowania
    SK i renumeracji po kompakcji. `ts` to ISO 8601 UTC moment zapisu.
    """

    role: Literal["user", "assistant"]
    content: str
    turn_idx: int = Field(..., ge=0)
    ts: str  # ISO 8601 UTC


class UsedRecipe(BaseModel):
    """Recipe wybrany przez RAG i użyty w odpowiedzi LLM.

    PR1 placeholder — zawsze `[]` w response (forward-compat dla PR2,
    gdy retriever będzie zwracał kandydatów z bazy przepisów).
    """

    slug: str
    name: str
    kcal: int
    similarity_score: float


class TokenUsage(BaseModel):
    """Anthropic API token usage z prompt caching breakdown.

    `cache_read_input_tokens` / `cache_creation_input_tokens` — z `usage`
    object Anthropic Messages API gdy `cache_control: ephemeral` aktywne
    (system prompt cached, dramatic latency + cost reduction).
    """

    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


class ChatResponse(BaseModel):
    """Top-level response dla `POST /api/advisor/chat`.

    `role` zawsze `"assistant"` (literal, dla type-safety frontend).
    `turn_idx` to indeks tej (assistant) tury w historii dnia. `tokens_used`
    + `generated_at` ustawiane przez handler post-LLM-call (LLM nie zna
    własnego znacznika czasu ani usage).
    """

    role: Literal["assistant"] = "assistant"
    content: str
    used_recipes: list[UsedRecipe] = Field(default_factory=list)
    turn_idx: int
    tokens_used: TokenUsage
    generated_at: str  # ISO 8601 UTC, np. "2026-05-07T19:23:45+00:00"
