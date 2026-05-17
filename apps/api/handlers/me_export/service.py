"""Service layer dla GET /api/me/export — dump całej PK USER#{id} jako JSON.

GDPR Art. 20 (data portability) — structured, commonly used, machine-readable.
Format: `{manifest: {...}, rows: [...]}`. Manifest agreguje counts per typ SK
(PROFILE/BIOMETRY/ACTIVITY/PLAN/ADVISOR_CACHE/CHAT/...) bez ujawniania content.

DDB Decimal → native JSON types (int gdy całkowite, inaczej float) per
`scripts/export_recipes_frontend.py` wzorzec.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from shared.dynamo import query_all_by_pk


def _decimal_to_native(obj: Any) -> Any:
    """Rekursywnie zamień Decimal → int (gdy integral) lub float.

    DDB serializuje liczby jako Decimal — JSON `json.dumps` nie umie tego
    bez `default=str`, ale string-cast traci numeryczną semantykę. Native
    conversion preserves JSON consumer ergonomics.
    """
    if isinstance(obj, list):
        return [_decimal_to_native(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _decimal_to_native(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    return obj


def _type_from_sk(sk: str) -> str:
    """Pierwszy segment SK przed `#` (np. `BIOMETRY#2026-05-01#hrv` → `BIOMETRY`)."""
    return sk.split("#", 1)[0] if "#" in sk else sk


def build_export(user_id: str) -> dict[str, Any]:
    """Zwróć pełny payload eksportu dla USER#{user_id}.

    Returns:
        {
          "manifest": {
            "user_id": ...,
            "generated_at": ISO 8601 UTC,
            "row_count": N,
            "types": {"BIOMETRY": ..., "ACTIVITY": ..., ...}
          },
          "rows": [<DDB items z native num types>]
        }

    `rows` zachowuje DDB-original kolejność (Query bez ScanIndexForward
    zwraca posortowane lexicographically po SK, co daje sensowny dump:
    ACTIVITY rows razem, BIOMETRY rows razem etc.).

    PK isolation: caller MUSI przekazać user_id z JWT (NIGDY z body/query).
    """
    raw_items = query_all_by_pk(f"USER#{user_id}")
    rows = [_decimal_to_native(item) for item in raw_items]

    types: dict[str, int] = {}
    for item in rows:
        sk = item.get("SK", "")
        type_key = _type_from_sk(sk)
        types[type_key] = types.get(type_key, 0) + 1

    return {
        "manifest": {
            "user_id": user_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "row_count": len(rows),
            "types": dict(sorted(types.items())),
        },
        "rows": rows,
    }
