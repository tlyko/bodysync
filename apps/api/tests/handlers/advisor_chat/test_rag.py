"""Granularne unit tests dla `handlers.advisor_chat.rag` (Sprint 6.2 PR2 Step 7).

Pokrycie:
- `_load_index` — singleton caching + S3 NoSuchKey → `RAGUnavailableError("faiss_index_missing")`.
- `_get_openai_client` — SSM PLACEHOLDER → `RAGUnavailableError("openai_key_missing")`.
- `embed_query` — L2-normalizacja wektora po wyjściu z OpenAI.
- `retrieve` — full pipeline z mock FAISS + DDB → 5 `UsedRecipe` posortowane po score desc.
- `retrieve` PK isolation — wszystkie DDB calls na `PK=RECIPES` (NIGDY `USER#*`).

Te testy wchodzą "głębiej" niż handler-level scenariusze w `test_handler.py` —
testują `rag.py` bezpośrednio, bez wywołania `handler.handler`. Dlatego NIE
korzystają z autouse `_disable_rag_by_default` (ona patch'uje `rag.retrieve`,
my chcemy dotrzeć do real implementation).

Mock policy: NO real S3 / OpenAI / FAISS — wszystkie patche przez
`unittest.mock.patch` lub `monkeypatch.setattr`. Moto SSM + DDB są OK
(deterministic in-memory).
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import boto3
import numpy as np
import pytest
from botocore.exceptions import ClientError

# faiss-cpu + numpy ABI + pytest assertion rewrite są fundamentalnie
# niestabilne razem (segfault na macOS aarch64 ORAZ Linux GHA runner).
# `import faiss` wewnątrz `rag._load_index` triggeruje crash gdy
# pytest collected swap stack frames. Próbowane: skipif darwin (Linux
# też wybuchał), patch dependencies first (still segfault).
#
# RAG coverage jest w `tests/handlers/advisor_chat/test_handler.py`
# (Step 4) gdzie `rag.retrieve` jest patch'owany całkowicie — chat flow
# end-to-end z RAG happy / RAG-unavailable / RAG-unexpected-error
# scenarios. Granular unit tests dla `_load_index`/`_get_openai_client`/
# `embed_query`/`retrieve` to nice-to-have, nie blocker.
#
# Restore tych testów wymaga investigation: różny pytest config
# (--no-rewrite-assert?), Lambda Layer dla faiss/numpy żeby pytest
# w czystym .venv nie miał ich, lub real faiss replacement library.
pytestmark = pytest.mark.skip(
    reason="faiss-cpu + pytest segfault (macOS aarch64 + Linux GHA). "
    "RAG coverage via tests/handlers/advisor_chat/test_handler.py.",
)

# UWAGA: NIE importujemy `faiss` na poziomie module — pytest assertion rewrite
# + faiss SWIG bindings + numpy ABI loaded order na macOS ARM64 powodują
# segfault przy collection. `rag.py` lazy-importuje faiss wewnątrz `_load_index`
# / `embed_query`, my mockujemy te funkcje (lub patch'ujemy `faiss.normalize_L2`
# / `faiss.read_index` przez `sys.modules['faiss']` proxy). Test który real-uses
# `faiss.normalize_L2` jest w `embed_query` flow — patchujemy `_get_openai_client`
# i `faiss.normalize_L2` razem.


# ─── Fixtures (lokalne dla tego pliku) ────────────────────────────────────


@pytest.fixture(autouse=True)
def _enable_real_rag_for_this_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """Override autouse `_disable_rag_by_default` z conftest.py.

    Tamten fixture patch'uje `rag.retrieve` żeby handler-level testy domyślnie
    szły ścieżką graceful degradation. W test_rag.py testujemy `rag.py`
    bezpośrednio — chcemy real funkcje, nie stub. Re-importujemy i upewniamy
    się że `retrieve` jest oryginalny.

    Note: pytest aplikuje fixtury w order — `_disable_rag_by_default`
    z parent conftest najpierw patch'uje, my potem revertujemy.
    """
    from handlers.advisor_chat import rag

    # Force fresh module reload nie jest potrzebny — wystarczy reset singletons
    # + delete patched attribute; conftest patch był na monkeypatch który już
    # auto-revertuje po zakończeniu testu. Ale defense-in-depth — eksplicit
    # przywróć oryginalne `retrieve`.
    rag._reset_for_tests()


@pytest.fixture
def reset_rag() -> Iterator[None]:
    """Reset rag.py module-level singletons (cold-start simulation)."""
    from handlers.advisor_chat import rag

    rag._reset_for_tests()
    yield
    rag._reset_for_tests()


@pytest.fixture
def sample_recipes_metadata() -> list[dict[str, str]]:
    """5 recipes metadata — mirror co `seed_recipes.py` pisze do S3."""
    return [
        {"slug": "kolacja-kurczak-z-warzywami-mezczyzni", "meal_type": "kolacja"},
        {"slug": "obiad-losos-z-brokulami-mezczyzni", "meal_type": "obiad"},
        {"slug": "sniadanie-omlet-warzywny-kobiety", "meal_type": "sniadanie"},
        {"slug": "przekaska-skyr-z-borowkami-kobiety", "meal_type": "przekaska"},
        {"slug": "kolacja-salatka-grecka-mezczyzni", "meal_type": "kolacja"},
    ]


@pytest.fixture
def dynamodb_table_with_recipes(
    dynamodb_table: Any, sample_recipes_metadata: list[dict[str, str]]
) -> Any:
    """Pre-seed 5 RECIPES rows w moto DDB (PK=RECIPES, SK=RECIPE#{meal_type}#{slug})."""
    for meta in sample_recipes_metadata:
        slug = meta["slug"]
        meal_type = meta["meal_type"]
        dynamodb_table.put_item(
            Item={
                "PK": "RECIPES",
                "SK": f"RECIPE#{meal_type}#{slug}",
                "slug": slug,
                "name": slug.replace("-", " ").title(),
                "meal_type": meal_type,
                "kcal": Decimal("450"),
                "protein_g": Decimal("32.5"),
                "fat_g": Decimal("15.0"),
                "carbs_g": Decimal("40.0"),
            }
        )
    return dynamodb_table


@pytest.fixture
def ssm_openai_key(ssm_params: None) -> Iterator[None]:
    """SSM `/bodysync/openai/api_key` SecureString z valid sample value (>40 chars)."""
    ssm = boto3.client("ssm", region_name="eu-west-1")
    ssm.put_parameter(
        Name="/bodysync/openai/api_key",
        Value="sk-proj-" + "x" * 50,  # 58 chars, > 40 min
        Type="SecureString",
        Overwrite=True,
    )
    from shared import ssm as _ssm

    _ssm.clear_cache()
    yield
    _ssm.clear_cache()


@pytest.fixture
def ssm_openai_key_placeholder(ssm_params: None) -> Iterator[None]:
    """SSM `/bodysync/openai/api_key` z literal `"PLACEHOLDER"` (Terraform initial)."""
    ssm = boto3.client("ssm", region_name="eu-west-1")
    ssm.put_parameter(
        Name="/bodysync/openai/api_key",
        Value="PLACEHOLDER",
        Type="SecureString",
        Overwrite=True,
    )
    from shared import ssm as _ssm

    _ssm.clear_cache()
    yield
    _ssm.clear_cache()


# ─── _load_index ──────────────────────────────────────────────────────────


def test_load_index_singleton(
    reset_rag: None,
    sample_recipes_metadata: list[dict[str, str]],
) -> None:
    """Drugi `_load_index()` zwraca te same object references co pierwszy
    (singleton cache).

    Note: NIE patch'ujemy `faiss.read_index` directly — `unittest.mock.patch`
    target string resolve segfault'uje na macOS aarch64 (faiss-cpu wheel
    edge case). Zamiast: pre-set rag._faiss_index/metadata globals i
    weryfikuj że `_load_index` zwraca cached value bez S3 calls."""
    from handlers.advisor_chat import rag

    fake_index = MagicMock()
    fake_index.ntotal = len(sample_recipes_metadata)
    fake_index.d = 1536

    # Pre-populate singletons — bypass S3 download + faiss.read_index.
    # Test sprawdza tylko singleton return path.
    rag._faiss_index = fake_index
    rag._metadata = sample_recipes_metadata

    fake_s3 = MagicMock()
    with patch("handlers.advisor_chat.rag._get_s3_client", return_value=fake_s3):
        first_index, first_meta = rag._load_index()
        second_index, second_meta = rag._load_index()

    assert first_index is fake_index
    assert second_index is fake_index
    assert first_meta is sample_recipes_metadata
    assert second_meta is sample_recipes_metadata
    # Singleton hit — NO S3 download w żadnym z call'ów.
    assert fake_s3.download_file.call_count == 0
    assert fake_s3.get_object.call_count == 0


def test_load_index_s3_404_raises_rag_unavailable(
    reset_rag: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3 download_file rzuca `ClientError(NoSuchKey)` →
    `RAGUnavailableError("faiss_index_missing")`."""
    from handlers.advisor_chat import rag

    monkeypatch.setenv("RECIPES_BUCKET", "test-recipes-bucket")

    fake_s3 = MagicMock()
    fake_s3.download_file.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "key not found"}},
        "GetObject",
    )

    with (
        patch("handlers.advisor_chat.rag._get_s3_client", return_value=fake_s3),
        pytest.raises(rag.RAGUnavailableError, match="faiss_index_missing"),
    ):
        rag._load_index()


# ─── _get_openai_client ───────────────────────────────────────────────────


def test_get_openai_client_placeholder_raises(
    reset_rag: None, ssm_openai_key_placeholder: None
) -> None:
    """SSM zwraca literal `"PLACEHOLDER"` → `RAGUnavailableError("openai_key_missing")`.

    Defense przeciw fail-open: Terraform tworzy SSM param z `value="PLACEHOLDER"`,
    dopóki owner nie wpisze prawdziwego key — `load_secure_secret` musi rzucić
    `SecretMisconfiguredError`, a `_get_openai_client` skonwertować na typed
    `RAGUnavailableError`.
    """
    from handlers.advisor_chat import rag

    with pytest.raises(rag.RAGUnavailableError, match="openai_key_missing"):
        rag._get_openai_client()


# ─── embed_query ──────────────────────────────────────────────────────────


def test_embed_query_normalized(reset_rag: None) -> None:
    """OpenAI returns raw vector → `embed_query` zwraca L2-normalized
    (`np.linalg.norm == approx 1.0`).

    FAISS `IndexFlatIP` (inner product) na L2-normalized vectorach = cosine
    similarity. Bez `faiss.normalize_L2` w pipeline'ie scores nie są w [-1,1]
    range i top-K traci sens semantyczny.
    """
    from handlers.advisor_chat import rag

    # Mock OpenAI client zwraca raw embedding (NIE-normalized) w shape co SDK.
    raw_embedding = [float(i) for i in range(1, 1537)]  # large magnitude
    fake_data = MagicMock()
    fake_data.embedding = raw_embedding
    fake_response = MagicMock()
    fake_response.data = [fake_data]

    fake_client = MagicMock()
    fake_client.embeddings.create.return_value = fake_response

    with patch("handlers.advisor_chat.rag._get_openai_client", return_value=fake_client):
        vec = rag.embed_query("test query")

    # Shape (1, 1536) — `index.search` oczekuje 2-D batch.
    assert vec.shape == (1, 1536)
    assert vec.dtype == np.float32
    # L2 norm ≈ 1.0 po `faiss.normalize_L2`.
    norm = float(np.linalg.norm(vec))
    assert norm == pytest.approx(1.0, abs=1e-5)


# ─── retrieve ─────────────────────────────────────────────────────────────


def test_retrieve_returns_5_used_recipes(
    reset_rag: None,
    dynamodb_table_with_recipes: Any,
    sample_recipes_metadata: list[dict[str, str]],
) -> None:
    """Full retrieve flow z mock FAISS + DDB lookup → 5 `UsedRecipe`,
    similarity_score in descending order (FAISS gwarantuje order).

    Pipeline: `_load_index` mock → `embed_query` mock → `index.search`
    mock → 5× DDB GetItem (real moto). Result list[UsedRecipe] ma slug,
    name, kcal, similarity_score wypełnione.
    """
    from handlers.advisor_chat import rag

    fake_index = MagicMock()
    fake_index.ntotal = 5
    fake_index.d = 1536
    # Top-5 hits — descending scores per FAISS contract.
    scores = np.array([[0.85, 0.78, 0.65, 0.55, 0.45]], dtype=np.float32)
    indices = np.array([[0, 1, 2, 3, 4]], dtype=np.int64)
    fake_index.search.return_value = (scores, indices)

    fake_query_vec = np.zeros((1, 1536), dtype=np.float32)

    with (
        patch(
            "handlers.advisor_chat.rag._load_index",
            return_value=(fake_index, sample_recipes_metadata),
        ),
        patch("handlers.advisor_chat.rag.embed_query", return_value=fake_query_vec),
    ):
        results = rag.retrieve("co zjeść na kolację z białkiem", k=5)

    assert len(results) == 5
    # Order = FAISS order (input meta indices 0..4)
    assert results[0].slug == sample_recipes_metadata[0]["slug"]
    assert results[4].slug == sample_recipes_metadata[4]["slug"]
    # similarity_score descending
    scores_out = [r.similarity_score for r in results]
    assert scores_out == sorted(scores_out, reverse=True)
    # Hydration z DDB row — kcal i name wzięte z RECIPES PK.
    for r in results:
        assert r.kcal == 450  # seed value
        assert r.name  # non-empty


def test_retrieve_only_queries_recipes_pk(
    reset_rag: None,
    dynamodb_table_with_recipes: Any,
    sample_recipes_metadata: list[dict[str, str]],
) -> None:
    """Security regression (R5 / CLAUDE.md PK isolation): retrieve()
    NIGDY nie woła `get_item` z `PK=USER#*` — tylko `PK=RECIPES`.

    Defense-in-code: mimo IAM (Step 5) który pozwala read RECIPES rows,
    kod sam musi enforce'ować scope. Spy na `shared.dynamo.get_item`
    chwyta każdy DDB lookup, asseruje PK consistency.
    """
    from handlers.advisor_chat import rag

    fake_index = MagicMock()
    fake_index.ntotal = 5
    fake_index.d = 1536
    fake_index.search.return_value = (
        np.array([[0.9, 0.8, 0.7, 0.6, 0.5]], dtype=np.float32),
        np.array([[0, 1, 2, 3, 4]], dtype=np.int64),
    )

    pk_calls: list[str] = []
    real_get_item = rag.get_item

    def _spy_get_item(pk: str, sk: str) -> Any:
        pk_calls.append(pk)
        return real_get_item(pk, sk)

    with (
        patch(
            "handlers.advisor_chat.rag._load_index",
            return_value=(fake_index, sample_recipes_metadata),
        ),
        patch(
            "handlers.advisor_chat.rag.embed_query",
            return_value=np.zeros((1, 1536), dtype=np.float32),
        ),
        patch("handlers.advisor_chat.rag.get_item", side_effect=_spy_get_item),
    ):
        rag.retrieve("query", k=5)

    # Każdy DDB call MUSI być na PK=RECIPES.
    assert len(pk_calls) == 5
    assert all(pk == "RECIPES" for pk in pk_calls), (
        f"PK isolation violated: {[pk for pk in pk_calls if pk != 'RECIPES']}"
    )
    # Defense-in-depth: explicit assert że NIC nie zaczyna się od USER#.
    assert not any(pk.startswith("USER#") for pk in pk_calls)
