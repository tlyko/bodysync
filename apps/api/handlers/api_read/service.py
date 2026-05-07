"""Service layer dla GET endpoints — DDB queries + aggregation."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from handlers.api_read.schemas import BiometryDay, MeResponse
from shared.dynamo import get_item, query_by_pk


class ProfileNotFoundError(Exception):
    """USER#{id} PROFILE row nie istnieje (user nigdy się nie zalogował)."""


def _to_python(value: Any) -> Any:
    """Decimal → int/float dla JSON response (DDB zwraca Decimal)."""
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    if isinstance(value, list):
        return [_to_python(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_python(v) for k, v in value.items()}
    return value


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
    """Pobiera wszystkie BIOMETRY rows dla user_id z ostatnich N dni,
    grupuje po date, agreguje per metric_name.

    Format SK z health_webhook handlera (Sprint 3):
      BIOMETRY#YYYY-MM-DD#metric_name             — single point upsert
      BIOMETRY#YYYY-MM-DD#metric_name#timestamp   — multi-point (HRV, HR)
    """
    today = datetime.now(UTC).date()
    cutoff_iso = (today - timedelta(days=days - 1)).isoformat()

    items = query_by_pk(f"USER#{user_id}", sk_prefix="BIOMETRY#")

    by_date: dict[str, dict[str, Any]] = defaultdict(dict)

    for raw in items:
        sk = raw["SK"]
        # Format: "BIOMETRY#date#metric" lub "BIOMETRY#date#metric#timestamp"
        parts = sk.split("#", 3)
        if len(parts) < 3:
            continue  # malformed, skip
        sk_date = parts[1]
        metric = parts[2]
        is_multipoint = len(parts) == 4

        if sk_date < cutoff_iso:
            continue

        attrs = {k: _to_python(v) for k, v in raw.items() if k not in ("PK", "SK")}

        if is_multipoint:
            # HRV / HR — append point z timestampem do listy
            day_metrics = by_date[sk_date].setdefault(metric, [])
            assert isinstance(day_metrics, list)
            day_metrics.append(attrs)
        else:
            by_date[sk_date][metric] = attrs

    # Sortowanie malejąco po dacie (najnowsze pierwsze)
    sorted_dates = sorted(by_date.keys(), reverse=True)
    return [BiometryDay(date=d, metrics=by_date[d]) for d in sorted_dates]


def _today_iso() -> str:
    """Test seam — pozwala mockować bieżącą datę w testach."""
    return date.today().isoformat()
