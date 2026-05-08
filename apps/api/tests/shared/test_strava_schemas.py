"""Tests dla `shared/strava.py` — Pydantic walidacja schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.strava import (
    EVENT_TTL_SECONDS,
    REFRESH_THRESHOLD_SECONDS,
    STATE_TTL_SECONDS,
    SYNTHETIC_SUBSCRIPTION_ID,
    StravaActivity,
    StravaTokens,
    StravaWebhookEvent,
)

# ─── Constants ─────────────────────────────────────────────────────────────


def test_constants_have_expected_values() -> None:
    """Sprawdza krytyczne stałe — zmiana wymaga uzasadnienia w PR."""
    assert STATE_TTL_SECONDS == 600  # 10 min
    assert REFRESH_THRESHOLD_SECONDS == 60
    assert EVENT_TTL_SECONDS == 7 * 24 * 3600  # 7 dni
    assert SYNTHETIC_SUBSCRIPTION_ID == 999999


# ─── StravaTokens ──────────────────────────────────────────────────────────


def test_tokens_validates_required_fields() -> None:
    with pytest.raises(ValidationError):
        StravaTokens.model_validate(
            {
                "access_token": "a",
                "refresh_token": "b",
                "expires_at": 1,
                # missing athlete_id
                "connected_at": 1,
            }
        )


def test_tokens_happy_path() -> None:
    t = StravaTokens(
        access_token="a",
        refresh_token="b",
        expires_at=1700000000,
        athlete_id=12345,
        connected_at=1699000000,
    )
    assert t.athlete_id == 12345


# ─── StravaWebhookEvent ────────────────────────────────────────────────────


def test_webhook_event_aspect_type_literal() -> None:
    """Literal['create', 'update', 'delete'] — inne wartości odrzucone."""
    with pytest.raises(ValidationError):
        StravaWebhookEvent.model_validate(
            {
                "object_type": "activity",
                "object_id": 1,
                "aspect_type": "wrong",  # invalid literal
                "owner_id": 1,
                "subscription_id": 1,
                "event_time": 1,
            }
        )


def test_webhook_event_object_type_literal() -> None:
    with pytest.raises(ValidationError):
        StravaWebhookEvent.model_validate(
            {
                "object_type": "segment",  # invalid (Strava tylko activity/athlete)
                "object_id": 1,
                "aspect_type": "create",
                "owner_id": 1,
                "subscription_id": 1,
                "event_time": 1,
            }
        )


def test_webhook_event_positive_ints() -> None:
    """object_id/owner_id/subscription_id/event_time muszą być > 0."""
    with pytest.raises(ValidationError):
        StravaWebhookEvent.model_validate(
            {
                "object_type": "activity",
                "object_id": 0,  # invalid (gt=0)
                "aspect_type": "create",
                "owner_id": 1,
                "subscription_id": 1,
                "event_time": 1,
            }
        )


def test_webhook_event_updates_default_empty() -> None:
    e = StravaWebhookEvent(
        object_type="activity",
        object_id=12345,
        aspect_type="create",
        owner_id=99,
        subscription_id=1,
        event_time=1700000000,
    )
    assert e.updates == {}


# ─── StravaActivity ────────────────────────────────────────────────────────


def test_activity_extra_fields_ignored() -> None:
    """Strava sends ~80 fieldów; extra='ignore' = walidacja nie wybucha."""
    a = StravaActivity.model_validate(
        {
            "id": 1,
            "name": "Test",
            "sport_type": "Run",
            "type": "Run",
            "distance": 5000.0,
            "moving_time": 1800,
            "elapsed_time": 1900,
            "total_elevation_gain": 50.0,
            "start_date": "2026-05-08T18:00:00Z",
            "start_date_local": "2026-05-08T20:00:00",
            "timezone": "(GMT+02:00) Europe/Warsaw",
            # extra fieldy — Strava rzeczywiście je wysyła
            "segment_efforts": [],
            "laps": [],
            "photos": {"primary": None},
            "achievement_count": 0,
            "kudos_count": 5,
        }
    )
    assert a.id == 1
    assert a.distance == 5000.0


def test_activity_optional_fields_default_none() -> None:
    a = StravaActivity.model_validate(
        {
            "id": 1,
            "name": "Test",
            "sport_type": "Walk",
            "type": "Walk",
            "distance": 0.0,
            "moving_time": 0,
            "elapsed_time": 0,
            "start_date": "2026-05-08T18:00:00Z",
            "start_date_local": "2026-05-08T20:00:00",
            "timezone": "Europe/Warsaw",
        }
    )
    assert a.calories is None
    assert a.average_heartrate is None
    assert a.has_heartrate is False
    assert a.total_elevation_gain == 0.0


def test_activity_missing_required_fails() -> None:
    with pytest.raises(ValidationError):
        StravaActivity.model_validate(
            {
                "id": 1,
                # missing name, sport_type, type, distance, moving_time, ...
            }
        )
