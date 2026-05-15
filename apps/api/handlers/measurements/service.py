"""Service layer dla POST /api/measurements — PutItem per metric do DDB.

SK format: `BIOMETRY#{date}#{metric}#manual` — `#manual` suffix differentiates
od HAE samples (które mają timestamp suffix `+02:00` per source-specific
bucketing). Owner może mieć HAE waga (`BIOMETRY#2026-05-14#weight`) i
manual obwody (`BIOMETRY#2026-05-14#waist#manual`) tego samego dnia
bez kolizji.

Per-metric PutItem (NIE BatchWriteItem) bo:
1. Max 5 items per request — boto3 retry cost pomijalny.
2. Partial failure semantics jaśniejsze — caller widzi które metryki się
   zapisały, które nie (mimo że w MVP zwracamy 500 na pierwszy error).
3. Idempotent — same metric/date PutItem overwrite'uje (last-write-wins),
   user może poprawić pomiar w ramach dnia bez DELETE.
"""

from __future__ import annotations

import time

from shared.dynamo import put_item


def save_measurements(
    user_id: str,
    date: str,
    measurements: dict[str, float],
) -> dict[str, bool]:
    """Zapisz każdą metryczkę jako osobny BIOMETRY row.

    Args:
        user_id: scope PK (USER#{user_id}) — caller MUSI użyć JWT-extracted
            user_id, NIGDY z body (CLAUDE.md "Reguła PK isolation").
        date: YYYY-MM-DD (regex-validated upstream w schemas).
        measurements: mapa `{metric_name: cm_value}`, np. `{"waist": 85.5}`.
            Klucze BEZ `_cm` suffix (handler strip'uje przed wywołaniem).

    Returns:
        Mapa `{metric_name: True}` per zapisana metryka. Pusty dict gdy
        `measurements` empty (caller nie powinien wywołać — schemas walidator
        chroni).
    """
    recorded_at = int(time.time())
    saved: dict[str, bool] = {}
    for metric, value in measurements.items():
        sk = f"BIOMETRY#{date}#{metric}#manual"
        attrs = {
            "cm": value,
            "source": "manual",
            "recorded_at": recorded_at,
        }
        put_item(f"USER#{user_id}", sk, attrs)
        saved[metric] = True
    return saved
