"""Strava fetcher service — token refresh + activity/streams fetch + persist.

Triggered by DDB Streams INSERT events na EVENT#strava partition. Każdy
record = jeden Strava webhook event (activity create/update/delete).

Flow per record:
1. Filter (defense-in-depth z Terraform filter_criteria) — PK/object_type/aspect.
2. Read user_id z record (zapisane przez webhook handler po athlete map lookup).
3. Load tokens z SSM `/bodysync/strava/{user_id}/tokens`.
4. Refresh access_token jeśli `expires_at - now < 60s`.
5. GET activity → StravaActivity (Pydantic).
6. GET streams (best-effort — failure → log + skip streams, persist activity).
7. PutObject streams.json do S3 raw bucket.
8. PutItem DDB `PK=USER#{user_id} SK=ACTIVITY#{strava_id}`.

Per-record try/catch w handler — błąd nie przerywa batch.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx
from boto3.dynamodb.types import TypeDeserializer

from shared.dynamo import put_item
from shared.s3 import archive_raw_payload
from shared.ssm import get_param, put_param
from shared.strava import REFRESH_THRESHOLD_SECONDS, StravaActivity, StravaTokens

STRAVA_TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"
STRAVA_ACTIVITY_URL = "https://www.strava.com/api/v3/activities/{id}"
STRAVA_STREAMS_URL = "https://www.strava.com/api/v3/activities/{id}/streams"
STREAM_KEYS = "heartrate,cadence,watts,time,distance,altitude,velocity_smooth"

CLIENT_ID_PARAM = "/bodysync/strava/client_id"
CLIENT_SECRET_PARAM = "/bodysync/strava/client_secret"
RAW_BUCKET_ENV = "RAW_BUCKET_NAME"

_deserializer = TypeDeserializer()


class FetcherSkipError(Exception):
    """Record skipped — defensive guard, log + continue."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def unmarshal_record(record: dict[str, Any]) -> dict[str, Any]:
    """Wyciąga relevant fields z DDB Streams NewImage (typed attribute format).

    Returns flat dict: PK, SK, user_id, object_id, object_type, aspect_type,
    owner_id, event_time, subscription_id. Brakujące → KeyError handled w
    process_activity_event.
    """
    new_image = (record.get("dynamodb") or {}).get("NewImage") or {}
    return {k: _deserializer.deserialize(v) for k, v in new_image.items()}


def tokens_ssm_path(user_id: str) -> str:
    return f"/bodysync/strava/{user_id}/tokens"


def load_tokens(user_id: str) -> StravaTokens:
    raw = get_param(tokens_ssm_path(user_id))
    return StravaTokens.model_validate_json(raw)


def save_tokens(user_id: str, tokens: StravaTokens) -> None:
    put_param(tokens_ssm_path(user_id), tokens.model_dump_json(), secure=True)


def refresh_if_expired(user_id: str, tokens: StravaTokens) -> StravaTokens:
    """Returns existing tokens if still fresh, lub fresh tokens po refresh.

    Strava rotuje refresh_token przy każdym refresh (Best Current Practice
    OAuth 2.1) — persistujemy nowy refresh_token w SSM żeby kolejny refresh
    nie failował z `invalid_grant`.
    """
    now = int(time.time())
    if tokens.expires_at - now > REFRESH_THRESHOLD_SECONDS:
        return tokens

    client_id = get_param(CLIENT_ID_PARAM, decrypt=False)
    client_secret = get_param(CLIENT_SECRET_PARAM)

    with httpx.Client(timeout=10.0) as client:
        resp = client.post(
            STRAVA_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": tokens.refresh_token,
            },
        )
    if resp.status_code != 200:
        # NIE logujemy body (mogłoby zawierać partial token w error message).
        raise RuntimeError(f"strava_refresh_failed status={resp.status_code}")

    data = resp.json()
    fresh = StravaTokens(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_at=int(data["expires_at"]),
        athlete_id=tokens.athlete_id,
        connected_at=tokens.connected_at,
    )
    save_tokens(user_id, fresh)
    return fresh


def fetch_activity(activity_id: int, access_token: str) -> StravaActivity | None:
    """GET activity. 404 → None (Strava deletion race after webhook fire).

    Other 4xx/5xx → raise (caller logs + skip record).
    """
    url = STRAVA_ACTIVITY_URL.format(id=activity_id)
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise RuntimeError(f"strava_activity_status={resp.status_code}")
    return StravaActivity.model_validate(resp.json())


def fetch_streams(activity_id: int, access_token: str) -> dict[str, Any] | None:
    """GET streams (HR/cadence/watts/time/distance/altitude/velocity).

    Best-effort — failure → None (caller persistuje activity bez streams).
    """
    url = STRAVA_STREAMS_URL.format(id=activity_id)
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params={"keys": STREAM_KEYS, "key_by_type": "true"},
            )
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        return resp.json()  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        return None


def streams_s3_key(user_id: str, activity_id: int) -> str:
    """Path layout: `strava/streams/{user_id}/{activity_id}.json`."""
    return f"strava/streams/{user_id}/{activity_id}.json"


def persist_streams(user_id: str, activity_id: int, streams: dict[str, Any]) -> str:
    bucket = os.environ[RAW_BUCKET_ENV]
    key = streams_s3_key(user_id, activity_id)
    archive_raw_payload(
        bucket=bucket,
        key=key,
        body=json.dumps(streams).encode("utf-8"),
    )
    return key


def persist_activity(
    user_id: str,
    activity: StravaActivity,
    streams_key: str | None,
    fetched_at: int,
) -> None:
    """PutItem `PK=USER#{user_id} SK=ACTIVITY#{strava_id}` — overwrite-OK
    bo aspect=update zdarza się (np. Strava re-classifies sport_type)."""
    attrs: dict[str, Any] = {
        "strava_id": activity.id,
        "name": activity.name,
        "sport_type": activity.sport_type,
        "type": activity.type,
        "distance_m": activity.distance,
        "moving_time_s": activity.moving_time,
        "elapsed_time_s": activity.elapsed_time,
        "elevation_gain_m": activity.total_elevation_gain,
        "start_date": activity.start_date,
        "start_date_local": activity.start_date_local,
        "timezone": activity.timezone,
        "fetched_at": fetched_at,
    }
    if activity.calories is not None:
        attrs["calories"] = activity.calories
    if activity.average_heartrate is not None:
        attrs["average_heartrate"] = activity.average_heartrate
    if activity.max_heartrate is not None:
        attrs["max_heartrate"] = activity.max_heartrate
    if activity.has_heartrate:
        attrs["has_heartrate"] = activity.has_heartrate
    if activity.suffer_score is not None:
        attrs["suffer_score"] = activity.suffer_score
    if streams_key:
        attrs["streams_s3_key"] = streams_key
    # Sprint 10 A9 — encoded summary_polyline dla mapy thumbnail w UI.
    # Strava może zwrócić `map` z None polyline (np. zapisany WeightTraining
    # bez GPS) — tylko zapisujemy gdy faktycznie jest niepusta string.
    if activity.map is not None and activity.map.summary_polyline:
        attrs["summary_polyline"] = activity.map.summary_polyline

    put_item(
        pk=f"USER#{user_id}",
        sk=f"ACTIVITY#{activity.id}",
        attrs=attrs,
    )


def process_activity_record(record_data: dict[str, Any]) -> dict[str, Any] | None:
    """Validate + execute pełen flow per webhook event record.

    Returns dict z metryką do log'a (sport_type, strava_id, refreshed) lub
    None gdy record był skipped (skip already logged przed return).

    Caller (handler) catches FetcherSkipError + RuntimeError + Exception.
    """
    pk = record_data.get("PK")
    if pk != "EVENT#strava":
        # Defense-in-depth — Terraform filter_criteria też filtruje, ale
        # paranoia bo pojedyncze events z innych PK nie powinny eksplodować.
        raise FetcherSkipError("non_strava_pk")

    object_type = record_data.get("object_type")
    if object_type != "activity":
        raise FetcherSkipError(f"non_activity_object_type:{object_type}")

    aspect = record_data.get("aspect_type")
    if aspect == "delete":
        # MVP: nie usuwamy activity row z DDB (user history retention).
        # Jeśli będzie potrzeba — osobny krok future.
        raise FetcherSkipError("delete_aspect")

    user_id = record_data.get("user_id")
    object_id_raw = record_data.get("object_id")
    if not user_id or not object_id_raw:
        raise FetcherSkipError("missing_user_id_or_object_id")

    activity_id = int(object_id_raw)

    tokens = load_tokens(user_id)
    refreshed = tokens.expires_at - int(time.time()) <= REFRESH_THRESHOLD_SECONDS
    if refreshed:
        tokens = refresh_if_expired(user_id, tokens)

    activity = fetch_activity(activity_id, tokens.access_token)
    if activity is None:
        # Strava deletion race — webhook fire'd dla activity, user usunął
        # zanim fetcher zdążył. Nic do zrobienia.
        raise FetcherSkipError("activity_deleted_404")

    streams = fetch_streams(activity_id, tokens.access_token)
    streams_key: str | None = None
    if streams is not None:
        try:
            streams_key = persist_streams(user_id, activity_id, streams)
        except Exception:
            # S3 write failure → log + persist activity bez streams_key.
            # Activity sama w sobie ma value w UI — streams to nice-to-have
            # dla późniejszych analiz.
            streams_key = None

    persist_activity(user_id, activity, streams_key, fetched_at=int(time.time()))

    return {
        "user_id": user_id,
        "strava_id": activity_id,
        "sport_type": activity.sport_type,
        "refreshed_token": refreshed,
        "streams_persisted": streams_key is not None,
    }
