"""Service layer dla POST /api/measurements — PutItem per metric do DDB.

SK format: `BIOMETRY#{date}#{metric}#manual` — `#manual` suffix differentiates
od HAE samples (które mają timestamp suffix `+02:00` per source-specific
bucketing). Owner może mieć HAE waga (`BIOMETRY#2026-05-14#weight`) i
manual obwody (`BIOMETRY#2026-05-14#waist#manual`) tego samego dnia
bez kolizji.

Per metric attribute name mirror'uje HAE shape (waist→cm, kcal_in→kcal,
protein/fat/carbs→g) żeby api_read service mógł sumować bez special-case.
Read-side precedence: gdy obecny manual + HAE buckets dla cumulative
metric (kcal_in, protein, fat, carbs), api_read filtruje na source=="manual"
przed sum → manual nadpisuje HAE dla danego dnia.

Per-metric PutItem (NIE BatchWriteItem) bo:
1. Max 9 items per request (5 obwodów + kcal_in + 3 makro) — boto3 retry
   cost pomijalny.
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
    measurements: dict[str, tuple[str, float]],
) -> dict[str, bool]:
    """Zapisz każdą metryczkę jako osobny BIOMETRY row.

    Args:
        user_id: scope PK (USER#{user_id}) — caller MUSI użyć JWT-extracted
            user_id, NIGDY z body (CLAUDE.md "Reguła PK isolation").
        date: YYYY-MM-DD (regex-validated upstream w schemas).
        measurements: mapa `{metric_name: (attr_name, value)}`, np.
            `{"waist": ("cm", 85.5), "kcal_in": ("kcal", 2200)}`.
            Klucze BEZ unit suffix (handler strip'uje przed wywołaniem).
            attr_name = "cm" | "g" | "kcal" — mirror HAE row shape.

    Returns:
        Mapa `{metric_name: True}` per zapisana metryka. Pusty dict gdy
        `measurements` empty (caller nie powinien wywołać — schemas walidator
        chroni).
    """
    recorded_at = int(time.time())
    saved: dict[str, bool] = {}
    for metric, (attr_name, value) in measurements.items():
        sk = f"BIOMETRY#{date}#{metric}#manual"
        attrs = {
            attr_name: value,
            "source": "manual",
            "recorded_at": recorded_at,
        }
        put_item(f"USER#{user_id}", sk, attrs)
        saved[metric] = True
    return saved
