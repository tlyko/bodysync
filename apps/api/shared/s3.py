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
