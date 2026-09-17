"""RRF fusion — combine vector + BM25 rankings into one chunk list (§9, item 8).

Reciprocal Rank Fusion (Cormack et al. 2009), the standard score-free fusion:
score(d) = Σ over legs  1 / (K + rank_leg(d)),  K = 60.

Chosen over score normalization deliberately: BM25 magnitudes (unbounded,
corpus-dependent) and cosine similarities (0–1) are not comparable — RRF uses
only RANKS, so no normalization is ever needed.

Dedup is by ``chunk_id`` — both legs read the same Cognee chunk collection, so
IDs match (verified in tests/test_bm25.py). A chunk found by both legs gets a
boosted fused score, and ``contributed_by`` records WHICH legs found it —
per §9: "Track retrieval metadata so evaluation can determine which method
contributed each result."

Graph triplets are NOT fused here: they are a different evidence kind
(entities/relations, no chunk_id) with their own provenance label; the engine
renders them as separate [G*] context blocks. Fusion covers the two chunk
legs; the graph stays the third, separately-presented leg.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Standard RRF constant (from the original paper); rank 1 → 1/61 ≈ 0.0164.
RRF_K = 60


@dataclass
class FusedHit:
    """One chunk after fusion — carries every leg's score for observability."""

    chunk_id: str
    text: str
    document: str
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Cosine similarity when the vector leg found it; None for keyword-only.
    vector_score: float | None = None
    #: BM25 magnitude when the keyword leg found it; None for vector-only.
    bm25_score: float | None = None
    #: Final RRF score (ranking only — never compared to cosine/BM25 values).
    rrf_score: float = 0.0
    #: Which retrievers found this chunk: subset of {"vector", "bm25"}.
    contributed_by: list[str] = field(default_factory=list)

    @property
    def both_legs_agree(self) -> bool:
        """True when both retrieval legs independently surfaced this chunk."""
        return len(self.contributed_by) > 1


def rrf_fuse(vector_hits: list[Any], bm25_hits: list[Any], k: int = RRF_K) -> list[FusedHit]:
    """Fuse the vector and BM25 hit lists into one RRF-ranked list.

    ``vector_hits``/``bm25_hits`` are VectorHit/BM25Hit (same fields: chunk_id,
    text, document, metadata). Both are already best-first.
    """
    state: dict[str, dict[str, Any]] = {}

    for rank, hit in enumerate(vector_hits, start=1):
        entry = state.setdefault(
            hit.chunk_id,
            {
                "text": hit.text,
                "document": hit.document,
                "metadata": dict(hit.metadata),
                "vector_score": None,
                "bm25_score": None,
                "rrf": 0.0,
                "contributed_by": [],
                "best_rank": rank,
            },
        )
        entry["rrf"] += 1.0 / (k + rank)
        entry["vector_score"] = hit.score
        entry["contributed_by"].append("vector")

    for rank, hit in enumerate(bm25_hits, start=1):
        entry = state.setdefault(
            hit.chunk_id,
            {
                "text": hit.text,
                "document": hit.document,
                "metadata": dict(hit.metadata),
                "vector_score": None,
                "bm25_score": None,
                "rrf": 0.0,
                "contributed_by": [],
                "best_rank": rank,
            },
        )
        entry["rrf"] += 1.0 / (k + rank)
        entry["bm25_score"] = hit.score
        entry["contributed_by"].append("bm25")
        entry["best_rank"] = min(entry["best_rank"], rank)

    fused = [
        FusedHit(
            chunk_id=chunk_id,
            text=entry["text"],
            document=entry["document"],
            metadata=entry["metadata"],
            vector_score=entry["vector_score"],
            bm25_score=entry["bm25_score"],
            rrf_score=entry["rrf"],
            contributed_by=entry["contributed_by"],
        )
        for chunk_id, entry in state.items()
    ]
    # Best RRF first; ties broken by the best per-leg rank (deterministic).
    fused.sort(key=lambda h: (-h.rrf_score, _tiebreak(h)))
    return fused


def _tiebreak(hit: FusedHit) -> int:
    """Stable secondary sort: agreement first, then input order is stable anyway."""
    return 0 if hit.both_legs_agree else 1