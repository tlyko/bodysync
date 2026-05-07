"""Sleep `asleep` field backfill — jednorazowy script.

Pre-PR-#46 sleep rows zostały zapisane bez fallback `asleep = core+rem+deep`,
przez co mają `asleep=0` mimo że HAE wysłał poprawne `inBed`/`core`/`rem`/`deep`.
PR #46 dodał fallback przy zapisie ALE nie poprawia istniejących rows.

Ten script:
1. Query wszystkich USER#{id}/BIOMETRY#{date}#sleep rows
2. Filtr: `asleep == 0 AND inBed > 0 AND (core + rem + deep) > 0`
3. Recompute `asleep = core + rem + deep`
4. Update DDB row in-place (UpdateItem set `asleep`)

Usage (manual, owner odpala lokalnie z env AWS):
    python apps/api/scripts/recompute_sleep.py --dry-run    # default
    python apps/api/scripts/recompute_sleep.py --execute    # rzeczywisty update

Idempotent — drugi run znajdzie 0 candidates (po pierwszym execute asleep>0).
"""

from __future__ import annotations

import argparse
import logging
import sys
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr, Key

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("recompute_sleep")

TABLE_NAME = "bodysync-data"
USERS = ["tomek", "weronika"]


def _scan_broken_sleep_rows(table: Any, user_id: str) -> list[dict[str, Any]]:
    """Query BIOMETRY#*#sleep dla user_id i filtruje po stronie clienta.

    KCE z `begins_with` zwraca wszystkie BIOMETRY rows; dalsze filtrowanie
    SK i atrybutów w Pythonie (mała baza, kosztowa OK).
    """
    response = table.query(
        KeyConditionExpression=Key("PK").eq(f"USER#{user_id}") & Key("SK").begins_with("BIOMETRY#"),
        FilterExpression=Attr("asleep").eq(Decimal("0")),
    )
    items = response.get("Items", [])
    sleep_only = [it for it in items if it["SK"].endswith("#sleep")]
    return sleep_only


def _is_recomputable(row: dict[str, Any]) -> bool:
    """Row ma sens recomputować jeśli inBed>0 i sumy stages>0."""
    in_bed = float(row.get("inBed", Decimal("0")))
    core = float(row.get("core", Decimal("0")))
    rem = float(row.get("rem", Decimal("0")))
    deep = float(row.get("deep", Decimal("0")))
    return in_bed > 0 and (core + rem + deep) > 0


def _recompute_asleep(row: dict[str, Any]) -> Decimal:
    core = row.get("core", Decimal("0"))
    rem = row.get("rem", Decimal("0"))
    deep = row.get("deep", Decimal("0"))
    return Decimal(str(float(core) + float(rem) + float(deep)))


def _update_row(table: Any, pk: str, sk: str, asleep: Decimal) -> None:
    table.update_item(
        Key={"PK": pk, "SK": sk},
        UpdateExpression="SET asleep = :a",
        ExpressionAttributeValues={":a": asleep},
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Wykonaj update (default: dry-run only).",
    )
    args = parser.parse_args()

    table = boto3.resource("dynamodb", region_name="eu-west-1").Table(TABLE_NAME)

    total_candidates = 0
    total_updated = 0

    for user_id in USERS:
        broken = _scan_broken_sleep_rows(table, user_id)
        candidates = [r for r in broken if _is_recomputable(r)]
        skipped = len(broken) - len(candidates)
        logger.info(
            "user=%s broken_total=%d recomputable=%d skipped_no_data=%d",
            user_id,
            len(broken),
            len(candidates),
            skipped,
        )
        for row in candidates:
            sk = row["SK"]
            new_asleep = _recompute_asleep(row)
            in_bed = float(row.get("inBed", 0))
            core = float(row.get("core", 0))
            rem = float(row.get("rem", 0))
            deep = float(row.get("deep", 0))
            logger.info(
                "  %s: inBed=%.2fh core=%.2f rem=%.2f deep=%.2f → asleep=%.2fh",
                sk,
                in_bed,
                core,
                rem,
                deep,
                float(new_asleep),
            )
            total_candidates += 1
            if args.execute:
                _update_row(table, f"USER#{user_id}", sk, new_asleep)
                total_updated += 1

    if args.execute:
        logger.info("DONE — updated %d rows", total_updated)
    else:
        logger.info(
            "DRY RUN — %d rows do update'owania. Powtórz z --execute żeby wykonać.",
            total_candidates,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
