"""DynamoDB single-table helpers.

PK isolation reminder: every read/write MUST scope to `USER#{user_id}` PK
(or known constant like `RECIPES`, `EVENT#strava`). NEVER pass user-supplied
PK without validation — see CLAUDE.md "Reguła PK isolation".

Read aggregations (Sprint 3.5):
- `sum_metric_today` / `sum_metric_in_range` — Query z `begins_with` na
  `BIOMETRY#{date}#{metric}#`, sum w aplikacji. Brak materialized view
  (per ADR-006 trade-off — N≤24 items/dzień/metric ≈ 1 RCU per Query).
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import boto3

_resource = boto3.resource("dynamodb")
_table_name = os.environ.get("TABLE_NAME", "bodysync-data")
_table = _resource.Table(_table_name)


def _to_dynamodb(value: Any) -> Any:
    """Konwertuje float → Decimal rekursywnie (DDB nie wspiera float).

    Pydantic models zwracają float dla numeric fields; bez konwersji boto3
    rzuca `TypeError: Float types are not supported`.
    """
    if isinstance(value, float):
        # str() — Decimal(float) ma rounding issues, str() zachowuje precyzję
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_dynamodb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_dynamodb(v) for v in value]
    return value


def get_item(pk: str, sk: str) -> dict[str, Any] | None:
    resp = _table.get_item(Key={"PK": pk, "SK": sk}, ConsistentRead=True)
    item = resp.get("Item")
    return dict(item) if item is not None else None


def put_item(pk: str, sk: str, attrs: dict[str, Any]) -> None:
    item = _to_dynamodb({"PK": pk, "SK": sk, **attrs})
    _table.put_item(Item=item)


def put_item_idempotent(pk: str, sk: str, attrs: dict[str, Any]) -> bool:
    """Conditional PutItem — fails silently on duplicate (returns False).

    Used for webhook idempotency tables where a replay must be a no-op.
    """
    item = _to_dynamodb({"PK": pk, "SK": sk, **attrs})
    try:
        _table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
        )
    except _resource.meta.client.exceptions.ConditionalCheckFailedException:
        return False
    return True


def delete_item_if_exists(pk: str, sk: str) -> dict[str, Any] | None:
    """Atomic single-use delete — returns old image lub None gdy brak.

    Używane dla CSRF state nonces (Sprint 4 Strava OAuth callback):
    sukces = state użyty raz; subsequent delete = None = invalid_state.
    `attribute_exists` ConditionalCheckFailedException → None (item nie istniał).
    """
    try:
        resp = _table.delete_item(
            Key={"PK": pk, "SK": sk},
            ConditionExpression="attribute_exists(PK)",
            ReturnValues="ALL_OLD",
        )
    except _resource.meta.client.exceptions.ConditionalCheckFailedException:
        return None
    return dict(resp.get("Attributes") or {}) or None


def batch_delete(keys: list[tuple[str, str]]) -> None:
    """Batch delete items by `(PK, SK)` tuples — używane przez chat history
    wipe (Sprint 11 prep — "Wyczyść rozmowę" przycisk).

    DDB `BatchWriteItem` ma limit 25 items per call; boto3 `batch_writer()`
    context manager auto-batch'uje + retry'uje unprocessed items. Dla
    typowej dziennej historii (≤ 60 turns = max 30 user × 30 assistant)
    to 2-3 batche, ~150-300ms total.

    Idempotent — DDB DeleteItem na nieistniejący item to no-op (no error).
    """
    if not keys:
        return
    with _table.batch_writer() as batch:
        for pk, sk in keys:
            batch.delete_item(Key={"PK": pk, "SK": sk})


def query_by_pk(pk: str, sk_prefix: str | None = None) -> list[dict[str, Any]]:
    """Query items for a given PK, optionally filtered by SK begins_with."""
    kwargs: dict[str, Any] = {"KeyConditionExpression": "PK = :pk"}
    expr_values: dict[str, Any] = {":pk": pk}
    if sk_prefix is not None:
        kwargs["KeyConditionExpression"] += " AND begins_with(SK, :skp)"
        expr_values[":skp"] = sk_prefix
    kwargs["ExpressionAttributeValues"] = expr_values
    resp = _table.query(**kwargs)
    return [dict(item) for item in resp.get("Items", [])]


def sum_metric_today(user_id: str, metric_short: str, *, value_attr: str, today: date) -> Decimal:
    """Suma `value_attr` po wszystkich hourly bucketach dla danego dnia.

    Query: `PK=USER#{user_id} AND begins_with(SK, "BIOMETRY#{today}#{metric_short}#")`.
    Returns `Decimal(0)` dla pustego setu — caller nie musi sprawdzać `None`.

    Sprint 3.5 design: read-time aggregation, brak materialized view.
    Dla N≤24 items/dzień/metric (typowy hourly granularity HAE) ≈ 1 RCU
    per Query. Cache pattern w ADR-006 (advisor on-demand endpoint).
    """
    sk_prefix = f"BIOMETRY#{today.isoformat()}#{metric_short}#"
    resp = _table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :skp)",
        ExpressionAttributeValues={":pk": f"USER#{user_id}", ":skp": sk_prefix},
    )
    total = Decimal("0")
    for item in resp.get("Items", []):
        raw = item.get(value_attr)
        if raw is None:
            continue
        # DDB zwraca Decimal; defensywne `Decimal(str(...))` na inne typy.
        total += raw if isinstance(raw, Decimal) else Decimal(str(raw))
    return total


def sum_metric_in_range(
    user_id: str,
    metric_short: str,
    *,
    value_attr: str,
    start: date,
    end: date,
) -> dict[str, Decimal]:
    """Per-day sumy w przedziale `[start..end]` (inclusive).

    Decyzja: prosty per-day loop > single Query z range filter — DDB nie
    ma `between` na fragment SK, pre-filter w aplikacji jest jaśniejszy.
    Max 7 dni dla weekly = 7 Query × ~3ms = pomijalne w cold-start budget.

    Returns dict `{date_iso: Decimal}` dla każdego dnia w przedziale
    (dni bez danych = `Decimal("0")`).
    """
    if start > end:
        raise ValueError(f"start {start} > end {end}")
    out: dict[str, Decimal] = {}
    cursor = start
    while cursor <= end:
        out[cursor.isoformat()] = sum_metric_today(
            user_id, metric_short, value_attr=value_attr, today=cursor
        )
        cursor += timedelta(days=1)
    return out
