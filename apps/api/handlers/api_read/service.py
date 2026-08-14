"""Service layer dla GET endpoints — DDB queries + mapowanie na schematy.

Agregacja BIOMETRY/WORKOUT siedzi w `shared/biometry.py` (wyciągnięta w PR MCP
#2), żeby handler MCP czytał te same dane tą samą logiką. Tutaj zostaje już
tylko mapowanie dict → model Pydantic i odczyt profilu.
"""

from __future__ import annotations

from typing import Any

from handlers.api_read.schemas import BiometryDay, MeResponse
from shared.biometry import aggregate_biometry_days, fetch_workouts
from shared.dynamo import get_item


class ProfileNotFoundError(Exception):
    """USER#{id} PROFILE row nie istnieje (user nigdy się nie zalogował)."""


def get_me(user_id: str) -> MeResponse:
    """Zwraca profile usera z DDB. Tworzony przez google_auth handler przy
    pierwszym loginie."""
    item = get_item(f"USER#{user_id}", "PROFILE")
    if item is None:
        raise ProfileNotFoundError(f"USER#{user_id}")
    return MeResponse(
        user_id=user_id,
        email=item["email"],
        name=item.get("name"),
    )


def get_biometry(user_id: str, *, days: int = 7) -> list[BiometryDay]:
    """BIOMETRY z ostatnich N dni, zagregowane per dzień i metrykę.

    Kształt odpowiedzi opisuje `shared.biometry.aggregate_biometry_days`.
    """
    return [BiometryDay(**day) for day in aggregate_biometry_days(user_id, days=days)]


def get_workouts(user_id: str, *, days: int = 30) -> list[dict[str, Any]]:
    """WORKOUT rows z ostatnich N dni, najnowsze pierwsze.

    Frontend grupuje per date dla "Historia wykonana" list view.
    """
    return fetch_workouts(user_id, days=days)
