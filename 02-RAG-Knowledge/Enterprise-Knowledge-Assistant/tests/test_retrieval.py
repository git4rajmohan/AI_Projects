"""Phase 7 retrieval tests (real services, real indexed corpus).

Skips cleanly when local services aren't running. These tests exercise the
actual Cognee-built Qdrant collection and the selected LLM provider — they are
slow (cloud LLM round-trip) but verify REAL grounded behavior, per plan.md.
"""

from __future__ import annotations

import pytest
import requests

from conftest import NOT_FOUND_PHRASES

from app.config.settings import get_settings
from app.retrieval.graph_retriever import GraphRetriever
from app.retrieval.hybrid_retriever import HybridRetriever
from app.retrieval.llamaindex_engine import LlamaIndexEngine
from app.retrieval.vector_retriever import CHUNK_COLLECTION, VectorRetriever

_KNOWN_QUESTION = "How many annual leave days do employees receive?"
_UNKNOWN_QUESTION = "What is the company's private jet travel policy?"
_RELATIONSHIP_QUESTION = "Which policy governs remote work?"


def _services_up() -> bool:
    """True when Qdrant + local embedding daemon are reachable."""
    settings = get_settings()
    try:
        requests.get(f"{settings.qdrant_url}/collections", timeout=3).raise_for_status()
        requests.post(
            f"{settings.local_base_url.rstrip('/')}/api/embed",
            json={"model": settings.embed_model, "input": "ping"},
            timeout=10,
        ).raise_for_status()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _services_up(), reason="local services not running")


@pytest.fixture(scope="module")
def engine() -> LlamaIndexEngine:
    return LlamaIndexEngine()


def test_collection_populated() -> None:
    """Precondition: the Phase 6 corpus is actually indexed."""
    from app.vectorstore import qdrant_manager

    info = qdrant_manager.get_collection_info(CHUNK_COLLECTION)
    assert info is not None, f"{CHUNK_COLLECTION} missing — run ingest first"
    assert info["points_count"] > 0


def test_vector_retrieval_returns_hits() -> None:
    """VectorRetriever returns real chunks with text and scores for a relevant query."""
    hits = VectorRetriever().retrieve(_KNOWN_QUESTION, top_k=3)
    assert len(hits) >= 1
    assert all(hit.text.strip() for hit in hits)
    assert all(hit.score >= 0.0 for hit in hits)
    # At least one hit must actually talk about leave (real evidence, not noise).
    assert any("leave" in hit.text.lower() or "vacation" in hit.text.lower() for hit in hits)


def test_relevant_question(engine: LlamaIndexEngine) -> None:
    """Groundedness — known question: relevant answer + at least one real source."""
    result = engine.answer(_KNOWN_QUESTION)
    assert result.answer.strip()
    assert result.vector_hits, "no evidence retrieved for a known question"
    assert result.sources, "citations must come from retrieved evidence"
    lower = result.answer.lower()
    # Grounded: the answer quotes a number or states leave info from evidence.
    assert any(tok in lower for tok in ("day", "leave", "vacation")), result.answer
    print("\nANSWER:", result.answer[:400])
    print("SOURCES:", result.sources)


def test_no_relevant_information(engine: LlamaIndexEngine) -> None:
    """Groundedness — unknown question: explicit not-found, no fabricated policy."""
    result = engine.answer(_UNKNOWN_QUESTION)
    lower = result.answer.lower()
    assert any(phrase in lower for phrase in NOT_FOUND_PHRASES), (
        f"LLM fabricated an answer: {result.answer[:300]}"
    )
    print("\nANSWER:", result.answer[:400])


def test_source_metadata(engine: LlamaIndexEngine) -> None:
    """Every citation filename exists in the corpus; no fabricated page numbers."""
    result = engine.answer(_KNOWN_QUESTION)
    known_docs = {p.name for p in get_settings().document_dir.glob("*.pdf")}
    for citation in result.citations:
        if citation.document == "unknown (provenance not resolvable)":
            continue  # recorded limitation, not a fabricated filename
        assert citation.document in known_docs, f"fabricated source {citation.document!r}"
        # §27: page only when real metadata provides it — Cognee chunks never do.
        assert citation.page is None, f"fabricated page number {citation.page!r}"
    assert result.citations, "known question must produce citations from evidence"


# -- Phase 10 + item 8: three-legged hybrid (vector + BM25 + graph) -------- #

def test_hybrid_retrieval(engine: LlamaIndexEngine) -> None:
    """End-to-end hybrid: answer uses RRF-fused chunks AND graph triplets,
    each keeping its own provenance (filenames vs 'knowledge graph')."""
    result = engine.answer("How are remote work and information security related?")
    assert result.vector_hits, "hybrid answer must have vector evidence"
    assert result.graph_hits, "hybrid answer must have graph evidence"
    assert result.citations, "citations must come from retrieved evidence"
    # Item 8: the fused ranking is the context authority.
    assert result.fused_hits, "RRF fusion must produce the context chunk list"
    lower = result.answer.lower()
    assert any(tok in lower for tok in ("remote", "security", "policy")), result.answer
    print("\nANSWER:", result.answer[:400])
    print("VECTOR SOURCES:", result.sources)
    print("FUSED ORDER:", [(h.chunk_id[:8], "+".join(h.contributed_by)) for h in result.fused_hits])
    print("GRAPH TRIPLETS:")
    for hit in result.graph_hits[:3]:
        print(f"  {hit.subject} --[{hit.relationship}]--> {hit.object}")


def test_hybrid_fusion_order_and_provenance() -> None:
    """Item 8 e2e: HybridRetriever returns per-leg rankings + fused ranking;
    dedupe by chunk_id holds; provenance (real filenames) preserved."""
    evidence = HybridRetriever().retrieve(_KNOWN_QUESTION, top_k=5)
    assert evidence.vector_hits, "vector leg empty"
    assert evidence.bm25_hits, "BM25 leg empty — keyword retrieval broken"
    assert evidence.fused_hits, "fusion produced nothing from two non-empty legs"
    assert not evidence.bm25_error and not evidence.graph_error

    # Union property: every fused chunk comes from at least one leg.
    leg_ids = {h.chunk_id for h in evidence.vector_hits} | {h.chunk_id for h in evidence.bm25_hits}
    fused_ids = {h.chunk_id for h in evidence.fused_hits}
    assert fused_ids <= leg_ids, "fused hits outside the union of leg hits"
    # Dedupe property: no duplicate chunk ids after fusion.
    assert len(fused_ids) == len(evidence.fused_hits), "duplicate chunk ids in fused list"
    # RRF ordering property: non-increasing scores.
    scores = [h.rrf_score for h in evidence.fused_hits]
    assert scores == sorted(scores, reverse=True), "fused list not RRF-ordered"
    # Per-leg contribution metadata (§9: which method contributed each result).
    for hit in evidence.fused_hits:
        assert hit.contributed_by, "contribution not tracked"
        assert set(hit.contributed_by) <= {"vector", "bm25"}
    # Citations still resolve to REAL filenames (graph-derived provenance).
    for hit in evidence.fused_hits:
        assert hit.document.endswith(".pdf") or hit.document.startswith("unknown"), (
            f"improvenanced document {hit.document!r}"
        )
    print("\nBM25 scores:", [round(h.score, 2) for h in evidence.bm25_hits])
    print("Fused:", [(h.chunk_id[:8], round(h.rrf_score, 4), "+".join(h.contributed_by))
                     for h in evidence.fused_hits])


def test_bm25_leg_contributes_keyword_hit_vector_misses() -> None:
    """The keyword leg must add value: for the exact policy-ID query, BM25
    surfaces the ID-bearing chunk; fusion keeps it even if the vector leg
    ranks it low (that's why the second leg exists)."""
    evidence = HybridRetriever().retrieve("ACME-HR-002 remote work policy", top_k=8)
    kw_ids = {h.chunk_id for h in evidence.bm25_hits}
    assert kw_ids, "BM25 leg found nothing for a policy-ID query"
    fused_ids = {h.chunk_id for h in evidence.fused_hits}
    assert kw_ids & fused_ids, "BM25-exclusive evidence dropped by fusion"
    print("\nBM25-only chunks kept:", len(kw_ids & fused_ids))

def test_graph_retrieval_returns_relationships() -> None:
    """GraphRetriever returns REAL (non-empty, non-fabricated) triplets for a
    relationship question. Plan.md Phase 9 groundwork for hybrid retrieval."""
    graph = GraphRetriever()
    hits = graph.retrieve(_RELATIONSHIP_QUESTION, top_k=5)
    assert hits, "graph retriever returned no relationships for a known question"
    for hit in hits:
        # Real triplets: subject/relationship/object all present, never fabricated.
        assert hit.subject.strip() and hit.object.strip()
        assert hit.relationship.strip()
        assert hit.metadata.get("source") == GraphRetriever.SOURCE_LABEL
    # The corpus genuinely covers remote work — evidence must mention it.
    joined = " ".join(f"{h.subject} {h.object}" for h in hits).lower()
    assert "remote" in joined or "work" in joined, f"unrelated triplets only: {hits[:3]}"
    print("\nGRAPH TRIPLETS:")
    for hit in hits[:3]:
        print(f"  {hit.subject} --[{hit.relationship}]--> {hit.object}")