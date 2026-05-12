"""Service layer dla waitlist signup — pojedynczy DDB put.

Schema:
    PK = WAITLIST
    SK = {iso_timestamp_utc_with_microseconds}#{email_lowercased}
    attrs = {email, interest, ip_hash, referrer, created_at}

Decyzja MVP: pomijamy idempotency check. Każdy resubmit = nowy rekord
(timestamp w SK się różni). Owner deduplikuje po `email` przy outreach.
Powód: alternatywą byłby Scan z FilterExpression (drogi, eventual
consistency) lub osobny GSI (overkill dla ~kilkudziesiąciu signupów).
KISS — duplikaty są tanie, dedup po stronie ownera trywialny.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from shared.dynamo import put_item

WAITLIST_PK = "WAITLIST"


def save_signup(
    email: str,
    interest: str | None,
    ip_hash: str,
    referrer: str | None,
    table_name: str | None = None,  # noqa: ARG001 — interface compat, used by shared.dynamo via env
) -> bool:
    """Wpisz signup do DDB pod PK=WAITLIST.

    SK encode'uje ts (sort chronologiczny w konsoli/CLI) + lowercased email
    (debug — owner widzi po kim pisać przy outreach). `table_name` jest
    nominalny w sygnaturze — `shared.dynamo` używa env var `TABLE_NAME`
    (wzór z innych handlerów); akceptowany dla future explicit injection.

    Returns True zawsze (MVP: brak idempotency check — patrz module docstring).
    Handler i tak zwraca 200 niezależnie od wyniku.
    """
    now = datetime.now(UTC)
    # Format ISO 8601 z mikrosekundami, sufiks 'Z' (RFC 3339 zulu).
    # Python `isoformat()` zwraca `+00:00` — replace dla zwięzłości.
    ts_iso = now.isoformat(timespec="microseconds").replace("+00:00", "Z")
    email_lower = email.lower()

    sk = f"{ts_iso}#{email_lower}"
    attrs: dict[str, object] = {
        "email": email_lower,
        "interest": interest,
        "ip_hash": ip_hash,
        "referrer": referrer,
        "created_at": int(time.time()),
    }
    put_item(WAITLIST_PK, sk, attrs)
    return True
