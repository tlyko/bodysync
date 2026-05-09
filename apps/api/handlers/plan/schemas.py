"""Pydantic schemas dla plan handler — response shape + cached row structure.

Sprint 5 MVP-LITE: zwracamy raw 2D array tekstowy (advisor parsuje semantycznie,
frontend renderuje table). Strukturalny parser → exercises objects post-MVP.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CachedPlan(BaseModel):
    """DDB shape dla `PK=USER#{id}` SK=`PLAN#current`.

    `rows` to surowa zawartość Google Sheet zakładki — list[list[str]],
    pusty cell jako "". Cell values zawsze string (Google Sheets API
    `valueRenderOption=FORMATTED_VALUE` default — liczby formatowane jak
    user widzi w UI).
    """

    model_config = ConfigDict(extra="forbid")

    rows: list[list[str]] = Field(default_factory=list)
    fetched_at: int = Field(..., description="Epoch seconds when row dump was pulled.")
    sheet_tab: str = Field(..., min_length=1, max_length=200)


class PlanResponse(BaseModel):
    """GET /api/plan response shape.

    `fresh=False` znaczy "z cache w DDB, nie świeże" — frontend może
    pokazać "ostatnio: 12 min temu" + przycisk odśwież. `fresh=True` ==
    just-fetched z Google Sheets.
    """

    model_config = ConfigDict(extra="forbid")

    rows: list[list[str]]
    fetched_at: int
    fresh: bool
    sheet_tab: str
