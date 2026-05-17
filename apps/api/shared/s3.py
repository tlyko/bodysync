"""S3 helpers — raw payload archive (HAE webhook, Strava streams).

KISS: brak kompresji. Lifecycle rule (IA → Glacier → expiration) robi
koszt znikomy. gzip dodaje per-key Content-Encoding + dependency complexity
bez dużej oszczędności na <5MB/payload.

Lazy boto3 client init — moduł importuje się szybko, klient tworzony
przy pierwszym użyciu (cold start budget, nie blokujemy przy import-time
gdy bucket env var nie jest jeszcze ustawiony).
"""

from __future__ import annotations

from typing import Any

import boto3

_client: Any = None  # boto3 S3 client; brak stubs w dev deps (ADR-002 — KISS)


def _get_client() -> Any:
    global _client
    if _client is None:
        _client = boto3.client("s3")
    return _client


def archive_raw_payload(
    bucket: str, key: str, body: bytes, *, content_type: str = "application/json"
) -> None:
    """Zapisuje raw payload do S3.

    Caller decyduje o kluczu (e.g. `raw/health-auto-export/{user}/{YYYY}/...`).
    Caller obsługuje wyjątki — best-effort archive nie blokuje webhooka.
    """
    _get_client().put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType=content_type,
    )


def delete_by_prefix(bucket: str, prefix: str) -> int:
    """Skasuj wszystkie obiekty pod prefix'em w S3 — returns count of deletes.

    Używane przez GDPR account erasure: `strava/streams/{user_id}/` +
    `raw/health-auto-export/{user_id}/`. List+batch delete (1000 keys per
    DeleteObjects). Idempotent — pusty prefix zwraca 0.

    Bucket NIE jest versioned (per s3.tf — versioning=Disabled), więc jeden
    DeleteObject = trwałe usunięcie. Gdy versioning włączymy później,
    trzeba bedzie też kasować NoncurrentVersions / DeleteMarkers.
    """
    client = _get_client()
    paginator = client.get_paginator("list_objects_v2")
    deleted = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
        if not keys:
            continue
        # DeleteObjects API limit: 1000 keys per call. ListObjectsV2 page
        # size = 1000 by default, więc każda strona = jeden DeleteObjects.
        client.delete_objects(Bucket=bucket, Delete={"Objects": keys, "Quiet": True})
        deleted += len(keys)
    return deleted
