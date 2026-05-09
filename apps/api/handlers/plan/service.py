"""Pure business logic dla plan handler — Google Sheets fetch + DDB cache.

Cache strategy:
- 15min TTL — owner zmiany w sheecie nie są real-time (trener update raz/tydz),
  ale frontend "odśwież" button może wymusić refetch (handler decyduje).
- Persistent fallback — gdy Google API down, serwujemy stale z DDB z
  `fresh=False`. Lepiej stale niż nic.
- Sheet name (tab) per-user w SSM — `Arkusz5` dla tomek, owner update gdy
  trenerka zmieni nazwę.
"""

from __future__ import annotations

import json
import time
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from handlers.plan.schemas import CachedPlan
from shared.dynamo import get_item, put_item

CACHE_TTL_SECONDS = 15 * 60  # 15 min — frontend force-refresh override możliwy

# Read-only — minimum scope (CLAUDE.md "scope minimal").
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


class PlanFetchError(Exception):
    """Google Sheets API zwrócił błąd lub credentials/config invalid.

    `reason` to fixed-vocabulary code (NIE Google error message — żeby nie
    leakować internal Google API details ani potentially-sensitive content
    z error response body, np. spreadsheet_id).
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def fetch_sheet_values(
    spreadsheet_id: str,
    sheet_tab: str,
    service_account_json: str,
) -> list[list[str]]:
    """GET spreadsheets.values z `range=sheet_tab` — całą zakładkę.

    `valueRenderOption` defaultuje na FORMATTED_VALUE — owner widzi
    formatted text w sheecie, my zachowujemy ten sam look (np. "5kg x 3 x 12"
    zamiast raw decimal). To ważne dla advisor RAG context.

    Returns 2D array z pustymi cellami jako "" (Google API zwraca jagged
    rows — krótszy row = puste komórki end-of-row pominięte; pad'ujemy).
    """
    try:
        creds_info = json.loads(service_account_json)
    except json.JSONDecodeError as e:
        raise PlanFetchError("invalid_credentials_json") from e

    # Lazy import — `google.oauth2.service_account` deps na cryptography
    # które ma cold-start cost (~150ms). Importujemy tylko gdy faktycznie
    # potrzebne (test path mockuje fetch_sheet_values whole, nie hits this).
    from google.oauth2 import service_account  # noqa: PLC0415

    try:
        credentials = service_account.Credentials.from_service_account_info(
            creds_info, scopes=SHEETS_SCOPES
        )
    except (ValueError, KeyError) as e:
        raise PlanFetchError("invalid_credentials_format") from e

    # `cache_discovery=False` — googleapiclient próbuje cache discovery doc
    # na fs, w Lambda /tmp warning + niepotrzebne dla single-call.
    service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

    try:
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=sheet_tab)
            .execute()
        )
    except HttpError as e:
        # 404 = sheet nie istnieje lub SA nie ma dostępu. 403 = scope/auth.
        # NIE logujemy spreadsheet_id ani body — fixed-vocabulary reason.
        status = getattr(e.resp, "status", None)
        if status == 404:
            raise PlanFetchError("sheet_not_found_or_no_access") from e
        if status == 403:
            raise PlanFetchError("permission_denied") from e
        raise PlanFetchError("sheets_api_error") from e
    except Exception as e:
        raise PlanFetchError("sheets_api_error") from e

    raw_rows: list[list[Any]] = result.get("values") or []
    if not raw_rows:
        return []

    # Pad jagged rows do max width + cast wszystko na str (Google Sheets
    # może zwrócić numbers as int/float gdy bez formatting; FORMATTED_VALUE
    # default to string ale defensywnie).
    max_width = max(len(r) for r in raw_rows)
    return [
        [str(c) if c is not None else "" for c in r] + [""] * (max_width - len(r)) for r in raw_rows
    ]


def load_cached_plan(user_id: str) -> CachedPlan | None:
    """DDB GetItem PK=USER#{id} SK=PLAN#current. None jeśli brak."""
    item = get_item(f"USER#{user_id}", "PLAN#current")
    if item is None:
        return None
    # PK/SK są częścią item ale nie chcemy ich w schema (extra="forbid").
    item.pop("PK", None)
    item.pop("SK", None)
    try:
        return CachedPlan.model_validate(item)
    except Exception:
        # Stale/corrupted cache row — traktuj jak miss, refetch wymusi clean.
        return None


def save_cached_plan(user_id: str, plan: CachedPlan) -> None:
    """DDB PutItem cache row."""
    put_item(f"USER#{user_id}", "PLAN#current", plan.model_dump())


def is_fresh(cached: CachedPlan, now_epoch: int | None = None) -> bool:
    """True jeśli cache jest młodsze niż CACHE_TTL_SECONDS."""
    now = now_epoch if now_epoch is not None else int(time.time())
    return (now - cached.fetched_at) < CACHE_TTL_SECONDS
