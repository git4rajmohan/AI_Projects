"""RRF fusion tests (item 8) — fully hermetic, no services needed.

Verifies the exact RRF math, dedupe-by-chunk_id, contribution tracking, and
that graph triplets are NOT fused (they're a separate evidence kind).
"""

from __future__ import annotations

from app.retrieval.bm25_retriever import BM25Hit
from app.retrieval.fusion import RRF_K, FusedHit, rrf_fuse
from app.retrieval.vector_retriever import VectorHit


def _vec(cid: str, score: float, doc: str = "a.pdf") -> VectorHit:
    return VectorHit(chunk_id=cid, text=f"vector text {cid}", score=score, document=doc)


def _kw(cid: str, score: float, doc: str = "a.pdf") -> BM25Hit:
    return BM25Hit(chunk_id=cid, text=f"vector text {cid}", score=score, document=doc)


def test_rrf_pure_vector_ranking() -> None:
    """Single-leg input keeps that leg's order with plain 1/(K+rank) scores."""
    fused = rrf_fuse([_vec("c1", 0.9), _vec("c2", 0.8)], [])
    assert [h.chunk_id for h in fused] == ["c1", "c2"]
    assert fused[0].rrf_score == 1.0 / (RRF_K + 1)
    assert fused[0].contributed_by == ["vector"]
    assert fused[0].vector_score == 0.9
    assert fused[0].bm25_score is None


def test_rrf_dedupes_by_chunk_id_and_boosts() -> None:
    """A chunk found by BOTH legs appears ONCE with a doubled RRF score."""
    # c1: rank 1 on vector, rank 2 on bm25 → 1/61 + 1/62
    fused = rrf_fuse([_vec("c1", 0.9), _vec("c2", 0.8)], [_kw("c9", 5.0), _kw("c1", 4.0)])
    ids = [h.chunk_id for h in fused]
    assert ids.count("c1") == 1, "duplicate chunk after fusion"
    c1 = next(h for h in fused if h.chunk_id == "c1")
    expected = 1.0 / (RRF_K + 1) + 1.0 / (RRF_K + 2)
    assert abs(c1.rrf_score - expected) < 1e-12
    assert c1.contributed_by == ["vector", "bm25"]
    assert c1.both_legs_agree is True
    assert c1.vector_score == 0.9 and c1.bm25_score == 4.0


def test_rrf_agreement_outranks_single_leg() -> None:
    """Both-legs agreement can beat a higher single-leg rank (RRF's point)."""
    # c3 rank-1 vector only: 1/61 = 0.01639
    # c1 rank-2 vector + rank-1 bm25: 1/62 + 1/61 = 0.03254 → wins
    fused = rrf_fuse([_vec("c3", 0.7), _vec("c1", 0.6)], [_kw("c1", 9.0)])
    assert fused[0].chunk_id == "c1"


def test_rrf_disjoint_legs_union() -> None:
    """Chunks unique to one leg still appear, with their leg's score recorded."""
    fused = rrf_fuse([_vec("v1", 0.8, "v.pdf")], [_kw("k1", 3.2, "k.pdf")])
    assert {h.chunk_id for h in fused} == {"v1", "k1"}
    v1 = next(h for h in fused if h.chunk_id == "v1")
    k1 = next(h for h in fused if h.chunk_id == "k1")
    assert v1.vector_score == 0.8 and v1.bm25_score is None
    assert k1.bm25_score == 3.2 and k1.vector_score is None
    assert v1.document == "v.pdf" and k1.document == "k.pdf"


def test_rrf_empty_inputs() -> None:
    assert rrf_fuse([], []) == []
    fused = rrf_fuse([], [_kw("k1", 1.0)])
    assert len(fused) == 1 and fused[0].contributed_by == ["bm25"]


def test_fused_hit_carries_metadata() -> None:
    vec = VectorHit(chunk_id="c1", text="t", score=0.5, document="a.pdf",
                    metadata={"collection": "DocumentChunk_text"})
    fused = rrf_fuse([vec], [])
    assert fused[0].metadata["collection"] == "DocumentChunk_text"


def test_graph_hits_never_enter_fusion() -> None:
    """GraphHit has no chunk_id — it's structurally impossible to fuse it here;
    the fusion contract only accepts chunk-shaped hits. Enforced by typing and
    by the engine building [G*] blocks separately (tested in test_retrieval)."""
    from app.retrieval.graph_retriever import GraphHit

    hit = GraphHit(subject="s", subject_type="Entity", relationship="r",
                   object="o", object_type="Entity")
    assert not hasattr(hit, "chunk_id")