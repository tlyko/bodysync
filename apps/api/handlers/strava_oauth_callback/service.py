"""Pure business logic dla strava_oauth_callback (separation: handler robi
I/O, service produkuje pure values + side effects przez injectowane deps).

Strava OAuth token exchange flow:
1. Frontend redirektuje user'a na Strava authorize → user kliknie OK →
   Strava redirektuje callback z `code` + `state`
2. Handler validate state z DDB (atomic delete)
3. Handler POST /oauth/token z code → tokens (access + refresh + athlete)
4. Handler persist tokens w SSM, update athlete-to-user map
"""

from __future__ import annotations

import json
import time

import httpx

from shared.strava import StravaTokens

STRAVA_TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"

# Frontend redirect po finished OAuth flow z `?strava=<status>` query param.
# Toast w UI pokaże komunikat na podstawie status'a.
FRONTEND_BASE_URL = "https://bodysync.pl"


class StravaTokenExchangeError(Exception):
    """Strava /oauth/token zwróciło błąd (invalid code, expired, network).

    `reason` to fixed-vocabulary code (NIE Strava error message — żeby
    nie loggować potentially-sensitive content z Strava response body).
    """

    def __init__(self, reason: str, status_code: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


class AthleteMapConflictError(Exception):
    """Athlete_id jest już mapped do innego user_id w SSM map.

    Wektor: gdy 2-user model się rozszerzy, drugi user nie może wejść
    przez OAuth z tym samym athlete_id (account takeover via webhook
    redirect). Owner musi ręcznie rozwiązać konflikt w SSM.
    """

    def __init__(self, athlete_id: int, existing_user_id: str, attempted_user_id: str) -> None:
        super().__init__(f"athlete_already_mapped:{athlete_id}")
        self.athlete_id = athlete_id
        self.existing_user_id = existing_user_id
        self.attempted_user_id = attempted_user_id


def exchange_code_for_tokens(code: str, client_id: str, client_secret: str) -> StravaTokens:
    """POST /oauth/token z `grant_type=authorization_code` → StravaTokens.

    Strava response shape (relevant fields):
    {
      "token_type": "Bearer",
      "access_token": "...",
      "refresh_token": "...",
      "expires_at": 1700000000,
      "expires_in": 21600,
      "athlete": {"id": 12345, "firstname": "...", ...}
    }
    """
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                STRAVA_TOKEN_URL,
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
    except httpx.HTTPError as e:
        raise StravaTokenExchangeError("network_error", 502) from e

    if resp.status_code != 200:
        # Strava zwraca 400 dla expired/invalid code. NIE logujemy body —
        # mogłoby zawierać client_id w error message lub partial token.
        raise StravaTokenExchangeError("strava_rejected", resp.status_code)

    try:
        data = resp.json()
    except json.JSONDecodeError as e:
        raise StravaTokenExchangeError("invalid_response", 502) from e

    athlete = data.get("athlete") or {}
    athlete_id = athlete.get("id")
    if not athlete_id:
        raise StravaTokenExchangeError("missing_athlete_id", 502)

    try:
        return StravaTokens(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=int(data["expires_at"]),
            athlete_id=int(athlete_id),
            connected_at=int(time.time()),
        )
    except (KeyError, ValueError, TypeError) as e:
        raise StravaTokenExchangeError("invalid_response", 502) from e


def update_athlete_map(existing_map_json: str, athlete_id: int, user_id: str) -> str:
    """Merge new athlete→user mapping w istniejący JSON SSM map.

    `existing_map_json` może być pusty `{}` (initial state) lub mapą z
    poprzednich OAuth flows. Returns JSON-serialized updated map.

    Raises AthleteMapConflictError gdy athlete_id jest już mapped do INNEGO
    user_id (re-OAuth tego samego user'a jest idempotent — no raise).
    """
    try:
        m = json.loads(existing_map_json) if existing_map_json else {}
    except json.JSONDecodeError:
        m = {}
    if not isinstance(m, dict):
        m = {}
    key = str(athlete_id)
    existing_user = m.get(key)
    if existing_user is not None and existing_user != user_id:
        raise AthleteMapConflictError(
            athlete_id=athlete_id,
            existing_user_id=str(existing_user),
            attempted_user_id=user_id,
        )
    m[key] = user_id
    return json.dumps(m, sort_keys=True)


def tokens_ssm_path(user_id: str) -> str:
    """Per-user SSM SecureString path dla persistowanych tokens."""
    return f"/bodysync/strava/{user_id}/tokens"


def frontend_redirect(status: str) -> str:
    """`https://bodysync.pl/?strava=<status>` — frontend pokaże toast."""
    return f"{FRONTEND_BASE_URL}/?strava={status}"
