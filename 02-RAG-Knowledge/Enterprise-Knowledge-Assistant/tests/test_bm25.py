"""BM25 retrieval tests (item 7, alternateplan.md §8 keyword leg).

Live tests run against the real Qdrant collection (read-only scroll). The
index builds once per test session via a module fixture; 131 chunks build
instantly.

Also verifies the KEYWORD advantage: an exact policy-ID query ("ACME-HR-002")
that semantic search handles poorly must rank correctly under BM25.
"""

from __future__ import annotations

import pytest
import requests

from app.config.settings import get_settings
from app.retrieval.bm25_retriever import BM25Retriever, tokenize
from app.retrieval.vector_retriever import CHUNK_COLLECTION


def _services_up() -> bool:
    settings = get_settings()
    try:
        requests.get(f"{settings.qdrant_url}/collections", timeout=3).raise_for_status()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _services_up(), reason="Qdrant not running")


@pytest.fixture(scope="module")
def bm25() -> BM25Retriever:
    retriever = BM25Retriever()
    size = retriever.build()
    print(f"\nBM25 index size: {size} chunks")
    return retriever


# -- Hermetic tokenizer tests --------------------------------------------- #
def test_tokenize_simple() -> None:
    assert tokenize("Remote Work Policy ACME-HR-002") == [
        "remote", "work", "policy", "acme", "hr", "002",
    ]


def test_tokenize_empty() -> None:
    assert tokenize("!!! ???") == []


# -- Live retrieval tests -------------------------------------------------- #
def test_bm25_index_built_from_real_corpus(bm25: BM25Retriever) -> None:
    """Index size equals the real chunk count in Qdrant (131 for this corpus)."""
    assert bm25.size > 0
    from app.vectorstore import qdrant_manager

    info = qdrant_manager.get_collection_info(CHUNK_COLLECTION)
    assert info is not None
    assert bm25.size == info["points_count"], (
        f"BM25 index has {bm25.size} docs but Qdrant has {info['points_count']} points"
    )


def test_bm25_keyword_query_hits_real_content(bm25: BM25Retriever) -> None:
    """A leave-policy keyword query returns chunks that really mention the terms."""
    hits = bm25.retrieve("annual leave vacation days", top_k=5)
    assert hits, "BM25 returned nothing for a keyword query the corpus contains"
    assert all(h.score > 0 for h in hits)
    assert any(
        "leave" in h.text.lower() or "vacation" in h.text.lower() for h in hits
    ), "top BM25 hits don't mention leave/vacation — ranking is broken"
    # Scores are BM25 magnitudes (unbounded), NOT cosine similarities.
    assert all(h.score < 100 for h in hits)
    print("\nBM25 scores:", [round(h.score, 3) for h in hits])


def test_bm25_exact_policy_id_advantage(bm25: BM25Retriever) -> None:
    """Exact terminology (policy ID) — the case BM25 exists for.

    The corpus documents carry IDs like ACME-HR-002; an exact-ID query must
    surface the matching chunk, demonstrating keyword retrieval where pure
    semantic search is weak (IDs embed poorly).
    """
    # Find a real policy ID from the corpus first (never fabricate one).
    from app.retrieval.vector_retriever import VectorRetriever

    import re

    probe = VectorRetriever().retrieve("official policy document", top_k=10)
    pattern = re.compile(r"ACME-[A-Z]{2}-\d{3}")
    found_id = None
    for hit in probe:
        m = pattern.search(hit.text)
        if m:
            found_id = m.group(0)
            break
    assert found_id, "no policy ID found in corpus — test premise broken"

    hits = bm25.retrieve(found_id, top_k=3)
    assert hits, f"BM25 found nothing for exact ID {found_id}"
    assert found_id.replace("-", "") in tokenize(hits[0].text) or found_id in hits[0].text, (
        f"top hit for {found_id} doesn't contain the ID"
    )
    print(f"\nExact ID {found_id} → top chunk of {hits[0].document}")


def test_bm25_no_overlap_query_returns_empty(bm25: BM25Retriever) -> None:
    """Zero term overlap ⇒ zero hits (score <= 0 filtered), not garbage."""
    hits = bm25.retrieve("zzzqxj nonexistentterm", top_k=5)
    assert hits == []


def test_bm25_dedupes_against_vector_hits(bm25: BM25Retriever) -> None:
    """Fusion prerequisite: chunk_ids from BM25 match vector retriever's IDs —
    RRF can dedupe by chunk_id (item 8) only if both legs use the same IDs."""
    from app.retrieval.vector_retriever import VectorRetriever

    bm25_hits = bm25.retrieve("remote work policy", top_k=5)
    vec_hits = VectorRetriever().retrieve("remote work policy", top_k=10)
    bm25_ids = {h.chunk_id for h in bm25_hits}
    vec_ids = {h.chunk_id for h in vec_hits}
    overlap = bm25_ids & vec_ids
    assert overlap, (
        "BM25 and vector legs share no chunk IDs — RRF dedupe by chunk_id would never fire"
    )
    print(f"\nID overlap between legs: {len(overlap)} chunks")