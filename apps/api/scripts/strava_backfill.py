"""Strava backfill CLI — one-time ingest ostatnich activities po OAuth.

Webhook subscription (`strava_subscribe.py`) łapie tylko **nowe** activities.
Backfill rozwiązuje UX: owner widzi historię natychmiast po Authorize.

Flow:
1. Read SSM `/bodysync/strava/{user_id}/tokens`.
2. GET `https://www.strava.com/api/v3/athlete/activities?per_page=N`
   z access_token (refresh jeśli expired).
3. Dla każdej activity → write synthetic `EVENT#strava` row z
   `subscription_id=SYNTHETIC_SUBSCRIPTION_ID=999999`.
4. DDB Stream + filter_criteria (PK=EVENT#strava) wystrzeli fetcher Lambda
   dla każdego — fetcher pobierze full activity + streams + persist do
   `USER#{user_id} ACTIVITY#{strava_id}`.

Uruchom:
    cd apps/api
    .venv/bin/python scripts/strava_backfill.py --user-id tomek --count 10

Idempotent — re-run nie psuje istniejących activities (fetcher overwrite-OK
dla `aspect_type=create`, idempotent put_item dla EVENT#strava SK z różnym
event_time per call → 2 events same activity, ale fetcher 2× write to same
DDB key = identical PutItem).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

import boto3
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("strava_backfill")

STRAVA_ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
STRAVA_TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"

SYNTHETIC_SUBSCRIPTION_ID = 999999
EVENT_TTL_SECONDS = 7 * 24 * 3600
REFRESH_THRESHOLD_SECONDS = 60


def tokens_ssm_path(user_id: str) -> str:
    return f"/bodysync/strava/{user_id}/tokens"


def read_tokens(user_id: str) -> dict[str, object]:
    raw = boto3.client("ssm", region_name="eu-west-1").get_parameter(
        Name=tokens_ssm_path(user_id), WithDecryption=True
    )["Parameter"]["Value"]
    return json.loads(raw)  # type: ignore[no-any-return]


def write_tokens(user_id: str, tokens: dict[str, object]) -> None:
    boto3.client("ssm", region_name="eu-west-1").put_parameter(
        Name=tokens_ssm_path(user_id),
        Value=json.dumps(tokens),
        Type="SecureString",
        Overwrite=True,
    )


def refresh_if_needed(user_id: str, tokens: dict[str, object]) -> dict[str, object]:
    expires_at = int(tokens["expires_at"])  # type: ignore[arg-type]
    if expires_at - int(time.time()) > REFRESH_THRESHOLD_SECONDS:
        return tokens

    ssm = boto3.client("ssm", region_name="eu-west-1")
    client_id = ssm.get_parameter(Name="/bodysync/strava/client_id")["Parameter"]["Value"]
    client_secret = ssm.get_parameter(Name="/bodysync/strava/client_secret", WithDecryption=True)[
        "Parameter"
    ]["Value"]

    resp = httpx.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
        },
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()
    fresh = {
        **tokens,
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": int(data["expires_at"]),
    }
    write_tokens(user_id, fresh)
    logger.info("Refreshed access_token for user_id=%s", user_id)
    return fresh


def fetch_recent_activities(access_token: str, count: int) -> list[dict]:
    resp = httpx.get(
        STRAVA_ACTIVITIES_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        params={"per_page": count, "page": 1},
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()  # type: ignore[no-any-return]


def write_synthetic_events(
    table_name: str,
    user_id: str,
    athlete_id: int,
    activities: list[dict],
) -> int:
    """Write 1 EVENT#strava row per activity z SYNTHETIC_SUBSCRIPTION_ID.

    Webhook handler po deploy będzie writeował z real subscription_id;
    backfill używa SYNTHETIC żeby webhook handler mógł odróżnić replay
    od real-time event (oba akceptowane).
    """
    table = boto3.resource("dynamodb", region_name="eu-west-1").Table(table_name)
    now = int(time.time())
    written = 0
    for a in activities:
        activity_id = a["id"]
        event_time = now
        sk = f"{SYNTHETIC_SUBSCRIPTION_ID}#{activity_id}#{event_time}"
        try:
            table.put_item(
                Item={
                    "PK": "EVENT#strava",
                    "SK": sk,
                    "user_id": user_id,
                    "owner_id": athlete_id,
                    "object_type": "activity",
                    "object_id": activity_id,
                    "aspect_type": "create",
                    "event_time": event_time,
                    "subscription_id": SYNTHETIC_SUBSCRIPTION_ID,
                    "ttl": event_time + EVENT_TTL_SECONDS,
                },
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
            written += 1
            logger.info(
                "queued synthetic event activity_id=%s name=%s",
                activity_id,
                a.get("name", "?")[:40],
            )
            # Rate limit lokalnie — DDB Stream batch-uje events, fetcher
            # invokuje raz na ~5s window. 10 activities = 1-2 batche.
            time.sleep(0.05)
        except Exception as e:
            logger.warning("skip activity_id=%s reason=%s", activity_id, e)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--user-id",
        required=True,
        help="bodysync user_id (e.g. 'tomek', 'weronika')",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Liczba ostatnich activities do backfill (default: 10, max 30)",
    )
    parser.add_argument(
        "--table",
        default="bodysync-data",
        help="DDB table name",
    )
    args = parser.parse_args(argv)

    if args.count < 1 or args.count > 30:
        logger.error("--count musi być 1..30")
        return 1

    logger.info("Loading tokens for user_id=%s", args.user_id)
    tokens = read_tokens(args.user_id)
    tokens = refresh_if_needed(args.user_id, tokens)

    athlete_id = int(tokens["athlete_id"])  # type: ignore[arg-type]
    access_token = tokens["access_token"]  # type: ignore[assignment]

    logger.info("Fetching %d most recent activities z Strava API", args.count)
    activities = fetch_recent_activities(access_token, args.count)  # type: ignore[arg-type]
    logger.info("Got %d activities", len(activities))

    if not activities:
        logger.warning("No activities returned — owner has empty Strava history?")
        return 0

    written = write_synthetic_events(args.table, args.user_id, athlete_id, activities)
    logger.info(
        "✓ Wrote %d synthetic events do DDB. Fetcher Lambda będzie ingestował "
        "via DDB Stream w ciągu ~5-30s. Sprawdź tab Aktywności.",
        written,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
