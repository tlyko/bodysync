"""Runtime RAG retrieval module dla `POST /api/advisor/chat` (Sprint 6.2 PR2 per ADR-007).

Cold-start lazy init:
- S3 download `recipes/faiss-index.bin` → `/tmp/faiss-index.bin` (~150ms)
- `faiss.read_index` (~50ms)
- S3 GetObject `recipes/recipes-metadata.json` (~30ms)
- `import faiss` (~300ms) — lazy wewnątrz `_load_index`, żeby unit tests
  service.py (które patch'ują `rag.retrieve`) nie płaciły tego kosztu.

Total ~500ms additional cold start (per ADR-007 D3).

Pipeline `retrieve(query, k)`:
1. lazy `_load_index` (singleton FAISS + metadata)
2. `embed_query` — OpenAI text-embedding-3-small (1536-dim, L2-normalized)
3. `index.search` — inner product = cosine na L2-normalized vectors
4. dla każdego top-K: DDB GetItem (RECIPES PK) → wyciąga `name`, `kcal`
5. zwraca `list[UsedRecipe]` (slug, name, kcal, similarity_score)

Failure modes (per ADR-007 graceful degradation OPEN-3):
- S3 missing FAISS / metadata → `RAGUnavailableError("faiss_index_missing")`
- OpenAI key PLACEHOLDER lub za krótki → `RAGUnavailableError("openai_key_missing")`
- OpenAI 5xx/timeout → `RAGUnavailableError("openai_embed_failed", status_code=...)`
- index ↔ metadata length mismatch → `RAGUnavailableError("index_metadata_mismatch")`

Caller (`handler.py`) łapie `RAGUnavailableError` i kontynuuje bez recipes
(handler składa prompt bez `<retrieved_recipes>` block).

Logging policy (ADR-007 OPEN-4): logujemy slug + similarity_score; NIE logujemy
recipe content (instructions, ingredients) ani user query content.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

import boto3
import numpy as np
from botocore.exceptions import ClientError

from shared.dynamo import get_item
from shared.logging import get_logger
from shared.ssm import SecretMisconfiguredError, load_secure_secret

from .schemas import UsedRecipe

if TYPE_CHECKING:
    import faiss
    from openai import OpenAI

logger = get_logger("advisor_chat.rag")

# ─── Constants ─────────────────────────────────────────────────────────────

FAISS_S3_KEY = "recipes/faiss-index.bin"
METADATA_S3_KEY = "recipes/recipes-metadata.json"
# Lambda /tmp 512MB ephemeral; FAISS index ~1-2MB safely fits.
LOCAL_FAISS_PATH = "/tmp/faiss-index.bin"  # noqa: S108
OPENAI_API_KEY_PARAM = "/bodysync/openai/api_key"
# OpenAI key prefix `sk-proj-` ~50+ chars; 40 jako sanity dolny limit.
OPENAI_API_KEY_MIN_LENGTH = 40
EMBEDDING_MODEL = "text-embedding-3-small"
RECIPES_BUCKET_ENV = "RECIPES_BUCKET"
# Top-K dla retrieve() (ADR-007 D6 — kompromis: 5 recipes ≈ 1500 tok input).
DEFAULT_TOP_K = 5

# ─── Module-level singletons (cold-start lazy init) ────────────────────────

_faiss_index: faiss.Index | None = None
_metadata: list[dict[str, str]] | None = None
_openai_client: OpenAI | None = None
# `Any` — boto3 stubs tylko w dev deps (mirror `shared/s3.py` patternu).
_s3_client: Any = None


# ─── Errors ────────────────────────────────────────────────────────────────


class RAGUnavailableError(Exception):
    """RAG retrieval nie jest dostępny (S3 missing, OpenAI key, embed fail).

    Mirror `AdvisorBackendError` shape z `service.py`: `reason` to fixed
    vocabulary code (NIE SDK exception message), `status_code` opcjonalnie
    z OpenAI/AWS error. Handler łapie i kontynuuje bez recipes
    (graceful degradation per ADR-007 OPEN-3).
    """

    def __init__(self, reason: str, *, status_code: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


# ─── Singleton accessors ───────────────────────────────────────────────────


def _get_s3_client() -> Any:
    """Lazy boto3 S3 client singleton."""
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3")
    return _s3_client


def _load_index() -> tuple[faiss.Index, list[dict[str, str]]]:
    """Lazy singleton: download FAISS + metadata z S3 raz per cold start.

    Idempotent — drugi call zwraca te same object references.

    Raises:
      RAGUnavailableError: brak env `RECIPES_BUCKET`, S3 NoSuchKey, lub
        index/metadata length mismatch (data integrity).
    """
    global _faiss_index, _metadata
    if _faiss_index is not None and _metadata is not None:
        return _faiss_index, _metadata

    bucket = os.environ.get(RECIPES_BUCKET_ENV)
    if not bucket:
        raise RAGUnavailableError("recipes_bucket_env_missing")

    # Lazy import faiss — unit testy service.py które patch'ują `rag.retrieve`
    # nie płacą ~300ms importu (per ADR-007 D3 cold-start budget).
    import faiss

    s3 = _get_s3_client()

    # Download FAISS index file → /tmp.
    try:
        s3.download_file(bucket, FAISS_S3_KEY, LOCAL_FAISS_PATH)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "Unknown")
        logger.error(
            "faiss_index_s3_download_failed",
            extra={"reason": "s3_error", "exc_type": "ClientError"},
        )
        if error_code in ("NoSuchKey", "NoSuchBucket", "404"):
            raise RAGUnavailableError("faiss_index_missing") from exc
        raise RAGUnavailableError("s3_error") from exc

    index = faiss.read_index(LOCAL_FAISS_PATH)

    # GetObject metadata.json (small file ~10-20KB, in-memory parse).
    try:
        resp = s3.get_object(Bucket=bucket, Key=METADATA_S3_KEY)
        metadata_raw = resp["Body"].read()
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "Unknown")
        logger.error(
            "metadata_s3_get_failed",
            extra={"reason": "s3_error", "exc_type": "ClientError"},
        )
        if error_code in ("NoSuchKey", "NoSuchBucket", "404"):
            raise RAGUnavailableError("faiss_index_missing") from exc
        raise RAGUnavailableError("s3_error") from exc

    metadata: list[dict[str, str]] = json.loads(metadata_raw)

    # Data integrity: każdy FAISS vector musi mieć metadata entry (i odwrotnie).
    # Mismatch sygnalizuje skorumpowany seed run lub partial S3 upload.
    if index.ntotal != len(metadata):
        raise RAGUnavailableError("index_metadata_mismatch")

    _faiss_index = index
    _metadata = metadata
    logger.info(
        "faiss_index_loaded",
        extra={"vector_count": index.ntotal, "dim": index.d},
    )
    return index, metadata


def _get_openai_client() -> OpenAI:
    """Lazy singleton — OpenAI SDK init + SSM key fetch raz per cold start.

    Raises:
      RAGUnavailableError("openai_key_missing"): SSM zwraca PLACEHOLDER lub
        key krótszy niż 40 chars (Terraform initial state).
    """
    global _openai_client
    if _openai_client is not None:
        return _openai_client
    try:
        api_key = load_secure_secret(OPENAI_API_KEY_PARAM, min_length=OPENAI_API_KEY_MIN_LENGTH)
    except SecretMisconfiguredError as exc:
        raise RAGUnavailableError("openai_key_missing") from exc

    # Lazy import — OpenAI SDK ~500ms import; nie chcemy płacić w testach
    # service.py które patch'ują rag.retrieve.
    from openai import OpenAI

    _openai_client = OpenAI(api_key=api_key, max_retries=2)
    return _openai_client


# ─── Embedding ─────────────────────────────────────────────────────────────


def embed_query(text: str) -> np.ndarray[Any, Any]:
    """Embed user query via OpenAI text-embedding-3-small + L2 normalize.

    L2 normalize jest wymagany — FAISS `IndexFlatIP` (inner product) na
    znormalizowanych wektorach = cosine similarity. Reshape (1, 1536) bo
    `index.search` oczekuje 2-D batch input.

    Raises:
      RAGUnavailableError("openai_key_missing"): SSM placeholder.
      RAGUnavailableError("openai_embed_failed", status_code): OpenAI 5xx/
        timeout/connection po retry. Drop exc body — `reason` to fixed code
        (per ADR-007 OPEN-4 — nie leakujemy promptów do logów).
    """
    client = _get_openai_client()

    # Lazy import dla exception types — uniknięcie pełnego openai importu
    # gdy klient już zcache'owany (drugi call do retrieve()).
    import faiss
    from openai import APIConnectionError, APIStatusError, APITimeoutError

    try:
        resp = client.embeddings.create(model=EMBEDDING_MODEL, input=text)
    except APIStatusError as exc:
        raise RAGUnavailableError(
            "openai_embed_failed", status_code=getattr(exc, "status_code", None)
        ) from exc
    except APITimeoutError as exc:
        raise RAGUnavailableError("openai_embed_failed") from exc
    except APIConnectionError as exc:
        raise RAGUnavailableError("openai_embed_failed") from exc

    vec = np.array(resp.data[0].embedding, dtype=np.float32).reshape(1, -1)
    faiss.normalize_L2(vec)  # in-place
    return vec


# ─── Retrieval ─────────────────────────────────────────────────────────────


def retrieve(query: str, k: int = DEFAULT_TOP_K) -> list[UsedRecipe]:
    """Top-K recipes po cosine similarity z user query.

    Pipeline:
    1. Lazy load FAISS index + metadata (`_load_index`).
    2. Embed query via OpenAI (`embed_query`).
    3. `index.search(query_vec, k)` → top-K (scores, indices).
    4. Dla każdego idx: lookup metadata → DDB GetItem (`PK=RECIPES`,
       `SK=RECIPE#{meal_type}#{slug}`) → buduje UsedRecipe.

    FAISS może zwrócić `idx == -1` gdy index ma < k vectorów (edge case);
    skipujemy. Orphan metadata entries (slug w metadata ale brak DDB row)
    też skipujemy z log warning — graceful degradation > 503.

    Raises:
      RAGUnavailableError: każdy step (S3, OpenAI key, embed) — caller
        łapie i kontynuuje bez recipes.

    Returns:
      Lista `UsedRecipe` posortowana descending po similarity_score
      (FAISS gwarantuje order). Może być pusta jeśli wszystkie metadata
      entries to orphans (defensive — nie crashujemy chatu).
    """
    index, metadata = _load_index()
    query_vec = embed_query(query)

    scores, indices = index.search(query_vec, k)

    results: list[UsedRecipe] = []
    for score, idx in zip(scores[0], indices[0], strict=True):
        idx_int = int(idx)
        # FAISS zwraca -1 gdy index ma mniej vectorów niż k (edge case).
        if idx_int < 0:
            continue
        if idx_int >= len(metadata):
            # Defensywne: powinno być wykryte w `_load_index` integrity check,
            # ale na wypadek race condition z reload — skip + log.
            logger.warning(
                "metadata_index_out_of_range",
                extra={"reason": "out_of_range"},
            )
            continue
        meta = metadata[idx_int]
        slug = meta.get("slug")
        meal_type = meta.get("meal_type")
        if not slug or not meal_type:
            logger.warning(
                "metadata_entry_invalid",
                extra={"reason": "missing_slug_or_meal_type"},
            )
            continue

        item = get_item("RECIPES", f"RECIPE#{meal_type}#{slug}")
        if item is None:
            # Orphan: metadata wskazuje na recipe którego nie ma w DDB
            # (deleted post-seed?). Skip + log slug — bez crashu chatu.
            logger.warning(
                "recipe_orphan_in_metadata",
                extra={"reason": "ddb_missing"},
            )
            continue

        name = item.get("name")
        kcal_raw = item.get("kcal")
        if not isinstance(name, str) or kcal_raw is None:
            logger.warning(
                "recipe_attrs_invalid",
                extra={"reason": "missing_name_or_kcal"},
            )
            continue

        results.append(
            UsedRecipe(
                slug=slug,
                name=name,
                kcal=int(kcal_raw),
                similarity_score=float(score),
            )
        )

    logger.info(
        "rag_retrieve_complete",
        extra={
            "query_length": len(query),
            "limit": k,
            "results_count": len(results),
            "slugs": [r.slug for r in results],
            "top_score": float(scores[0][0]) if len(results) else 0.0,
        },
    )
    return results


# ─── Test seam ─────────────────────────────────────────────────────────────


def _reset_for_tests() -> None:
    """Test-only — drop singletons between tests."""
    global _faiss_index, _metadata, _openai_client, _s3_client
    _faiss_index = None
    _metadata = None
    _openai_client = None
    _s3_client = None


__all__ = [
    "DEFAULT_TOP_K",
    "EMBEDDING_MODEL",
    "FAISS_S3_KEY",
    "METADATA_S3_KEY",
    "OPENAI_API_KEY_PARAM",
    "RECIPES_BUCKET_ENV",
    "RAGUnavailableError",
    "_get_openai_client",
    "_load_index",
    "_reset_for_tests",
    "embed_query",
    "retrieve",
]
