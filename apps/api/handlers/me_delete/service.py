"""Service layer dla DELETE /api/me/account — cascade erasure (RODO Art. 17).

Order operacji jest WAŻNY — jeśli któryś krok się wywali, retry musi być
bezpieczny:

1. **DDB** — `query_all_by_pk(USER#{id})` → `batch_delete`. Najpierw bo gdy
   skasujemy SSM Strava tokens to fetcher nie odświeży, ale jeśli zostaną
   DDB ACTIVITY rows to user wciąż widzi historię — gorszy intermediate state.
2. **S3** — `delete_by_prefix` na `strava/streams/{user_id}/` +
   `raw/health-auto-export/{user_id}/`. Idempotent — pusty prefix = 0.
3. **SSM per-user keys** — Strava tokens, HAE webhook secret, training-sheet
   refs. `delete_param` idempotent.
4. **SSM JSON maps** — athlete-to-user, allowed_emails. Read → drop entries →
   write back. Conflict-free: 2-osobowy MVP, brak race condition (jeden user
   self-delete równolegle z drugim self-delete to corner case nie do MVP).

Wszystkie kroki best-effort cumulative — caller dostaje dict counts per
typ deleted. Jeden krok exception → 500 z partial state (logger pokaże który).
"""

from __future__ import annotations

import json
import os

from shared.dynamo import batch_delete, query_all_by_pk
from shared.s3 import delete_by_prefix
from shared.ssm import delete_param, get_param, put_param

STRAVA_TOKENS_TEMPLATE = "/bodysync/strava/{user_id}/tokens"
HAE_SECRET_TEMPLATE = "/bodysync/health-auto-export/webhook_secret_{user_id}"
SHEET_ID_TEMPLATE = "/bodysync/{user_id}/training-sheet-id"
SHEET_TAB_TEMPLATE = "/bodysync/{user_id}/training-sheet-tab"
ATHLETE_MAP_PARAM = "/bodysync/strava/athlete-to-user"
ALLOWED_EMAILS_PARAM = "/bodysync/auth/allowed_emails"

# S3 layout per health_webhook/handler.py + strava_fetcher/service.py.
S3_HAE_PREFIX = "raw/health-auto-export/{user_id}/"
S3_STRAVA_PREFIX = "strava/streams/{user_id}/"


def _delete_ddb_partition(user_id: str) -> int:
    """Query całej USER#{id} + batch_delete. Returns count of deleted rows."""
    rows = query_all_by_pk(f"USER#{user_id}")
    keys = [(item["PK"], item["SK"]) for item in rows if "PK" in item and "SK" in item]
    batch_delete(keys)
    return len(keys)


def _delete_s3_objects(user_id: str) -> int:
    """Skasuj user-scoped raw payloads. Returns count of deleted objects.

    Bucket name from env (`RAW_BUCKET_NAME`). Mirror handler/health_webhook +
    strava_fetcher env layout.
    """
    bucket = os.environ.get("RAW_BUCKET_NAME")
    if not bucket:
        # Brak bucket = nic do kasowania (np. testy z disabled S3 archiwum).
        return 0
    total = 0
    total += delete_by_prefix(bucket, S3_HAE_PREFIX.format(user_id=user_id))
    total += delete_by_prefix(bucket, S3_STRAVA_PREFIX.format(user_id=user_id))
    return total


def _delete_ssm_per_user(user_id: str) -> int:
    """Kasuje 4 per-user SSM keys. Returns count of actually deleted."""
    paths = [
        STRAVA_TOKENS_TEMPLATE.format(user_id=user_id),
        HAE_SECRET_TEMPLATE.format(user_id=user_id),
        SHEET_ID_TEMPLATE.format(user_id=user_id),
        SHEET_TAB_TEMPLATE.format(user_id=user_id),
    ]
    return sum(1 for path in paths if delete_param(path))


def _prune_athlete_map(user_id: str) -> int:
    """Read athlete-to-user JSON map → drop entries `value == user_id`.

    Returns count of removed mappings (typowo 0 lub 1 — user połączył
    1 Strava account). Brak mapy / niepoprawny JSON → 0 (idempotent dla
    świeżego usera).
    """
    try:
        raw = get_param(ATHLETE_MAP_PARAM, decrypt=False)
    except Exception:
        return 0
    try:
        m = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return 0
    if not isinstance(m, dict):
        return 0
    pruned = {k: v for k, v in m.items() if v != user_id}
    removed = len(m) - len(pruned)
    if removed > 0:
        put_param(ATHLETE_MAP_PARAM, json.dumps(pruned, sort_keys=True), secure=False)
    return removed


def _prune_allowed_emails(user_id: str) -> int:
    """Read allowed_emails JSON list → drop entries gdzie `user_id` matches.

    Returns count of removed entries (typowo 0 lub 1). Konsekwencja: po
    erasure user nie zaloguje się ponownie bez owner ponownie wpisującego
    email w allowliście (RODO compliant — explicit re-consent).
    """
    try:
        raw = get_param(ALLOWED_EMAILS_PARAM, decrypt=False)
    except Exception:
        return 0
    try:
        entries = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        return 0
    if not isinstance(entries, list):
        return 0
    pruned = [e for e in entries if not (isinstance(e, dict) and e.get("user_id") == user_id)]
    removed = len(entries) - len(pruned)
    if removed > 0:
        put_param(ALLOWED_EMAILS_PARAM, json.dumps(pruned), secure=False)
    return removed


def erase_account(user_id: str) -> dict[str, int]:
    """Full cascade erasure dla USER#{user_id}.

    PK isolation: caller MUSI przekazać user_id z JWT.

    Returns counts dict — caller loguje + zwraca w response. Idempotent:
    re-call dla już skasowanego usera zwraca `{... : 0, ...}`.
    """
    return {
        "ddb_rows": _delete_ddb_partition(user_id),
        "s3_objects": _delete_s3_objects(user_id),
        "ssm_user_keys": _delete_ssm_per_user(user_id),
        "athlete_map_entries": _prune_athlete_map(user_id),
        "allowed_emails_entries": _prune_allowed_emails(user_id),
    }
