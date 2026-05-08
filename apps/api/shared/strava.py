"""Pure helpers + Pydantic schemas dla Strava integration (Sprint 4).

Brak I/O — handlers reading/writing SSM/DDB użują własnych modułów (`shared.ssm`,
`shared.dynamo`). Tu tylko schemas + constants do walidacji input'u.

Schemas mirror Strava API response shapes (best-effort, `extra='ignore'` żeby
~80 fieldów per activity nie zatrzymało walidacji gdy Strava doda nowe).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# OAuth state TTL — DDB row znika po 10 min (CSRF nonce should be short-lived).
STATE_TTL_SECONDS = 600

# Refresh access token jeśli expires_at - now < 60s. Strava access token żyje
# ~6h; refresh token żyje aż do explicit revoke.
REFRESH_THRESHOLD_SECONDS = 60

# Webhook event row (`PK=EVENT#strava`) idempotency window — DDB native TTL
# wymiata po 7 dniach żeby nie kumulować śmieci. Strava rzadko replay-uje
# >24h ago.
EVENT_TTL_SECONDS = 7 * 24 * 3600

# Replay marker — `scripts/strava_replay.py` wstawia ten id zamiast prawdziwego
# subscription_id w syntetycznych eventach żeby webhook handler mógł odróżnić
# real od test (oba akceptowane, ale logujemy `replay=True`).
SYNTHETIC_SUBSCRIPTION_ID = 999999


class StravaTokens(BaseModel):
    """OAuth access + refresh tokens persistowane w SSM SecureString
    `/bodysync/strava/{user_id}/tokens` jako JSON.

    `connected_at` zapisujemy raz przy callback; `expires_at` aktualizowane
    przy każdym refresh.
    """

    access_token: str
    refresh_token: str
    expires_at: int
    athlete_id: int
    connected_at: int


class StravaWebhookEvent(BaseModel):
    """Body POST /api/strava/webhook. Strava docs:
    https://developers.strava.com/docs/webhooks/

    Wszystkie 6 fieldów są obowiązkowe per Strava spec — odrzucamy
    malformed (handler logguje warn i zwraca 200 żeby Strava nie retry-owała).
    """

    object_type: Literal["activity", "athlete"]
    object_id: int = Field(gt=0)
    aspect_type: Literal["create", "update", "delete"]
    owner_id: int = Field(gt=0)
    subscription_id: int = Field(gt=0)
    event_time: int = Field(gt=0)
    updates: dict[str, Any] = Field(default_factory=dict)


class StravaActivity(BaseModel):
    """Subset Strava activity response który nas interesuje.

    Strava /api/v3/activities/{id} zwraca ~80 fieldów (segment_efforts,
    laps, photos, splits_metric, ...). Tu tylko core które trafią do DDB.
    `extra='ignore'` — nowe Strava fields nie wybuchają walidacji.
    """

    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    sport_type: str
    type: str
    distance: float
    moving_time: int
    elapsed_time: int
    total_elevation_gain: float = 0.0
    start_date: str
    start_date_local: str
    timezone: str
    calories: float | None = None
    average_heartrate: float | None = None
    max_heartrate: float | None = None
    has_heartrate: bool = False
    suffer_score: float | None = None
    perceived_exertion: float | None = None
