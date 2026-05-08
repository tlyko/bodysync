"""Eksportuje recipes z DDB `PK=RECIPES` do JSON pod `apps/web/src/recipes.json`.

Frontend (Sprint 7) renderuje RecipeCard z full metadanymi (ingredients,
instructions, makro) bez round-trip do backendu — chat response zwraca tylko
`used_recipes: [{slug, name, kcal, similarity_score}]`, UI matchuje slug
w lokalnej mapie i pokazuje pełne dane.

Re-run idempotent: sortowanie po slug + ensure_ascii=False + indent=2 →
deterministic diff. Re-run po `seed_recipes.py` (corpus update) generuje
nowy snapshot, commit-uj.

Usage:
    python scripts/export_recipes_frontend.py
    python scripts/export_recipes_frontend.py --output-path /tmp/recipes.json
    python scripts/export_recipes_frontend.py --table bodysync-data
"""

from __future__ import annotations

import argparse
import json
import logging
from decimal import Decimal
from pathlib import Path
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("export_recipes")

# Skip atrybutów które są server-side only (PK/SK technical, embedding_text =
# raw text z którego liczymy embedding — frontend nie potrzebuje).
INTERNAL_ATTRS = {"PK", "SK", "embedding_text"}

# Domyślny path względem repo root — script wola się z apps/api/.
# parents[3] = repo root: scripts/[2]=apps/api → [3]=apps → ojej, parents[3] = bodysync/.
# Ścieżka pliku: bodysync/apps/api/scripts/export_recipes_frontend.py
#   parents[0] = scripts/, [1] = api/, [2] = apps/, [3] = bodysync/.
DEFAULT_OUTPUT = Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "recipes.json"


def _decimal_to_native(obj: Any) -> Any:
    """Convert boto3 Decimal → int|float, recurse list/dict.

    DDB Number → boto3 Decimal w resource API. JSON nie umie Decimal,
    musimy zdjąć przed dump. int gdy nie ma części dziesiętnej, inaczej float.
    """
    if isinstance(obj, list):
        return [_decimal_to_native(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _decimal_to_native(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    return obj


def query_all_recipes(table_name: str) -> list[dict[str, Any]]:
    """Query DDB `PK=RECIPES` z paginacją (fallback gdy >1MB)."""
    table = boto3.resource("dynamodb").Table(table_name)
    items: list[dict[str, Any]] = []
    last_key: dict[str, Any] | None = None
    while True:
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("PK").eq("RECIPES"),
        }
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
    return items


def clean_recipe(item: dict[str, Any]) -> dict[str, Any]:
    """Strip internal attrs + decimal → native, return dict ordered po slug."""
    cleaned = {k: _decimal_to_native(v) for k, v in item.items() if k not in INTERNAL_ATTRS}
    return cleaned


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-path",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Path do JSON output (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--table",
        default="bodysync-data",
        help="DDB table name (default: bodysync-data)",
    )
    args = parser.parse_args()

    logger.info("query DDB %s PK=RECIPES", args.table)
    raw_items = query_all_recipes(args.table)
    logger.info("fetched %d recipes", len(raw_items))

    cleaned = [clean_recipe(item) for item in raw_items]
    cleaned.sort(key=lambda r: r["slug"])

    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    with args.output_path.open("w", encoding="utf-8") as f:
        json.dump(cleaned, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")  # trailing newline for git friendliness

    size_kb = args.output_path.stat().st_size / 1024
    logger.info("wrote %s (%.1f KB, %d recipes)", args.output_path, size_kb, len(cleaned))


if __name__ == "__main__":
    main()
