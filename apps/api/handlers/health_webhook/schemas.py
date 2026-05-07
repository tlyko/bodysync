"""Pydantic schemas dla payloadu Health Auto Export.

HAE używa nietypowego formatu daty: `"YYYY-MM-DD HH:mm:ss ±ZZZZ"` (spacja
zamiast `T`). Pydantic natywnie tego nie sparsuje — `BeforeValidator`
przepuszcza string przez `datetime.strptime`.

Top-level schema (`HAEPayload`) trzyma luźny `data: list[dict]` per metric,
bo HAE ma 100+ metric names z różnymi shape'ami (scalar `qty`, heart rate
`Min/Avg/Max`, sleep z 10+ sub-fields). Discriminated union by się
rozjechał za każdym iOS releasem. Service layer rozdziela per `metric.name`
z explicit allowlistą.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

HAE_DATE_FORMAT = "%Y-%m-%d %H:%M:%S %z"


def _parse_hae_date(v: str | datetime) -> datetime:
    if isinstance(v, datetime):
        return v
    return datetime.strptime(v, HAE_DATE_FORMAT)


HAEDateTime = Annotated[datetime, BeforeValidator(_parse_hae_date)]


class HAEScalarPoint(BaseModel):
    """Większość metryk: pojedyncza wartość `qty` z timestampem.

    HRV (ms), kroki, kcal, waga, body fat, dietary energy/protein/carbs/fat.
    """

    model_config = ConfigDict(extra="allow")  # forward-compat — nowe iOS pola OK
    qty: float
    date: HAEDateTime
    source: str | None = None


class HAEMetric(BaseModel):
    """Jeden segment HAE payloadu — `name` + lista raw points.

    `data` to `list[dict]` bo różne metric names mają różne shape'y
    (HRV ma `qty`, heart_rate ma `Min/Avg/Max`, sleep_analysis ma 10+ pól).
    Service layer parsuje raw dicts per `name` w odpowiedni Pydantic typ.
    """

    model_config = ConfigDict(extra="allow")
    name: str = Field(min_length=1, max_length=64)
    units: str | None = None
    data: list[dict[str, Any]]


class HAEData(BaseModel):
    metrics: list[HAEMetric] = Field(default_factory=list)
    workouts: list[dict[str, Any]] = Field(default_factory=list)  # MVP: silent drop


class HAEPayload(BaseModel):
    data: HAEData
