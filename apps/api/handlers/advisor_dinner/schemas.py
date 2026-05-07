"""Pydantic schemas dla `POST /api/advisor/dinner` (Sprint 6 MVP per ADR-006).

Request: free-text `notes` opcjonalne (sanityzowane via `<user_note>` wrap
w prompt). User_id z JWT cookie, brak field w body — defense przeciw IDOR.

Response: `summary` (3-5 zdań po polsku) + macros target + `today_state`
snapshot (debug + transparency) + 3 `suggestions` (konkretne propozycje
kolacji). `cached`/`generated_at` ustawiane post-call w handler — Anthropic
tool_use `input_schema` widzi tylko fields od LLM (patrz `service.py`).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DinnerAdvisorRequest(BaseModel):
    """Body dla `POST /api/advisor/dinner`.

    `notes` to free-text wskazówka od user'a — np. "jadłem ciastko o 16,
    nie głodny". Wrap w `<user_note>` z explicit prompt-injection guard
    w system promp (patrz `system_prompt.txt`). Max 500 chars — wystarczy
    na realistyczną wskazówkę, blokuje payload bombs.
    """

    notes: str | None = Field(default=None, max_length=500)


class TodayState(BaseModel):
    """Snapshot dzisiejszych metryk widziany przez LLM. Frontend renderuje
    jako collapsible debug, LLM używa do uzasadnienia propozycji.

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


class DinnerSuggestion(BaseModel):
    """Pojedyncza propozycja kolacji generowana przez LLM."""

    name: str
    kcal: int
    protein_g: int
    fat_g: int
    carbs_g: int
    description: str  # 1-2 zdania, składniki + krótka instrukcja
    why: str  # 1 zdanie — dlaczego pasuje do dziś (kontekst)


class DinnerAdvisorResponse(BaseModel):
    """Top-level response. `cached`/`generated_at` ustawiane przez handler
    post-LLM-call (LLM nie zna własnego znacznika czasu ani cache state).
    """

    summary: str  # 3-5 zdań po polsku, voice-able
    target_dinner_kcal: int
    target_dinner_protein_g: int
    target_dinner_fat_g: int
    target_dinner_carbs_g: int
    today_state: TodayState
    suggestions: list[DinnerSuggestion] = Field(min_length=1, max_length=5)
    generated_at: str  # ISO 8601 UTC, np. "2026-05-07T19:23:45+00:00"
    cached: bool


class DinnerAdvisorLLMOutput(BaseModel):
    """Subset DinnerAdvisorResponse — tylko fields LLM faktycznie generuje.

    `today_state` wstawia handler (server-side z DDB), `cached`/`generated_at`
    też handler. Anthropic tool_use `input_schema` używa tej klasy żeby model
    nie zgadywał `today_state` (LLM mógłby zwymyślać kcal — server widzi
    rzeczywiste DDB rows).
    """

    summary: str
    target_dinner_kcal: int
    target_dinner_protein_g: int
    target_dinner_fat_g: int
    target_dinner_carbs_g: int
    suggestions: list[DinnerSuggestion] = Field(min_length=1, max_length=5)
