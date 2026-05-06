"""DynamoDB single-table helpers.

PK isolation reminder: every read/write MUST scope to `USER#{user_id}` PK
(or known constant like `RECIPES`, `EVENT#strava`). NEVER pass user-supplied
PK without validation — see CLAUDE.md "Reguła PK isolation".
"""

from __future__ import annotations

import os
from typing import Any

import boto3

_resource = boto3.resource("dynamodb")
_table_name = os.environ.get("TABLE_NAME", "bodysync-data")
_table = _resource.Table(_table_name)


def get_item(pk: str, sk: str) -> dict[str, Any] | None:
    resp = _table.get_item(Key={"PK": pk, "SK": sk}, ConsistentRead=True)
    item = resp.get("Item")
    return dict(item) if item is not None else None


def put_item(pk: str, sk: str, attrs: dict[str, Any]) -> None:
    item = {"PK": pk, "SK": sk, **attrs}
    _table.put_item(Item=item)


def put_item_idempotent(pk: str, sk: str, attrs: dict[str, Any]) -> bool:
    """Conditional PutItem — fails silently on duplicate (returns False).

    Used for webhook idempotency tables where a replay must be a no-op.
    """
    item = {"PK": pk, "SK": sk, **attrs}
    try:
        _table.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
        )
    except _resource.meta.client.exceptions.ConditionalCheckFailedException:
        return False
    return True


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
