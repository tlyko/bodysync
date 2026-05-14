"""Pure helpers dla strava_oauth_start handlera.

Separation of concerns: handler robi I/O (JWT verify, DDB write, SSM read,
HTTP response), service produkuje pure values (state token, authorize URL).
"""

from __future__ import annotations

import secrets
import time
from urllib.parse import urlencode

from shared.dynamo import put_item
from shared.strava import STATE_TTL_SECONDS

# Strava OAuth scopes potrzebne dla bodysync:
# - `read` — basic profile (athlete id, firstname/lastname dla connection
#   status display)
# - `activity:read_all` — wszystkie activities (włącznie z private). Bez
#   `_all` Strava zwraca tylko publiczne, co dla niektórych userów = 0
#   bo domyślnie aktywności są private.
STRAVA_SCOPE = "read,activity:read_all"

# Hardcoded callback URL — Strava sprawdza match z `Authorization Callback
# Domain` w app settings. Nie używamy ENV bo to publiczna wartość bez
# variability cross-environment (single API GW custom domain).
STRAVA_CALLBACK_URL = "https://api.bodysync.pl/api/strava/oauth/callback"

# Standard OAuth authorize endpoint. Próbowaliśmy `/oauth/mobile/authorize`
# (PR #171) żeby native deep-link otworzył Strava app, ale Strava app rzuca
# "error" zaraz po kliknięciu "Authorize" — ten endpoint jest deprecated dla
# third-party developers (tylko Strava-owned apps mają OAuth flow w native UI).
# Browser flow z `/oauth/authorize` działa wszędzie; iOS pokazuje banner
# "Open in Strava" automatycznie jeśli user zalogowany w app.
STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"


def mint_state(user_id: str) -> str:
    """Generate cryptographically random state, persist w DDB pod
    PK=STRAVA_OAUTH_STATE#{state}, SK=META z TTL 10 min + user_id.

    State to single-use nonce — callback DeleteItem z `attribute_exists`
    condition zapewnia że ten sam state nie zostanie użyty dwukrotnie.

    Returns:
        URL-safe state token (~43 chars, 32 bytes random base64).
    """
    state = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + STATE_TTL_SECONDS
    put_item(
        pk=f"STRAVA_OAUTH_STATE#{state}",
        sk="META",
        attrs={
            "user_id": user_id,
            "ttl": expires_at,
        },
    )
    return state


def build_authorize_url(client_id: str, state: str) -> str:
    """Build Strava OAuth authorize URL.

    `approval_prompt=auto` — Strava nie prosi user'a o re-authorization
    jeśli już authorized z tym scope (KISS dla returning user).
    """
    params = {
        "client_id": client_id,
        "redirect_uri": STRAVA_CALLBACK_URL,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": STRAVA_SCOPE,
        "state": state,
    }
    return f"{STRAVA_AUTHORIZE_URL}?{urlencode(params)}"
