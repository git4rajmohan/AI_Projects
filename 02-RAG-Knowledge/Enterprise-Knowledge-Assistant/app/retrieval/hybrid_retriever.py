"""HybridRetriever — three-legged retrieval: vector + BM25 + graph (Phase 10+8).

Composition of the existing retrievers plus RRF fusion (fusion.py); no new
retrieval logic lives here:

* :class:`~app.retrieval.vector_retriever.VectorRetriever` — semantic chunks
  with REAL document provenance (filenames from the Cognee graph).
* :class:`~app.retrieval.bm25_retriever.BM25Retriever` — keyword chunks
  (exact terminology / policy IDs; alternateplan.md §8's BM25 leg).
* :class:`~app.retrieval.graph_retriever.GraphRetriever` — relationship
  triplets labeled ``"knowledge graph"``.

Chunk legs are fused with Reciprocal Rank Fusion (dedupe by chunk_id, per-leg
contribution tracked in ``FusedHit.contributed_by``). Graph triplets are NOT
fused into the chunk list — they are a different evidence kind and keep their
own provenance; the engine renders them as separate ``[G*]`` context blocks.

Provenance stays attached to the piece of evidence that owns it — nothing is
re-attributed or flattened into one undifferentiated list.

Degradation contract (unchanged from Phase 10): a graph failure degrades to
vector+BM25 with a recorded error; a BM25 failure degrades to vector-only with
a recorded error; a vector failure propagates (no chunks = no evidence).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.config.settings import Settings, get_settings
from app.retrieval.bm25_retriever import BM25Retriever
from app.retrieval.fusion import FusedHit, rrf_fuse
from app.retrieval.graph_retriever import GraphHit, GraphRetriever
from app.retrieval.vector_retriever import VectorHit, VectorRetriever

logger = logging.getLogger(__name__)


@dataclass
class HybridEvidence:
    """All evidence sets for one query; provenance preserved per piece.

    ``vector_hits`` keeps the pure semantic ranking (debug/eval per-leg
    visibility); ``fused_hits`` is the RRF-ranked union of vector+BM25 and is
    what the LLM context is built from.
    """

    #: Pure semantic ranking (kept for per-leg observability + the gate).
    vector_hits: list[VectorHit] = field(default_factory=list)
    #: Pure keyword ranking (per-leg observability).
    bm25_hits: list[BM25Hit] = field(default_factory=list)
    #: RRF fusion of the two chunk legs — the context-ordering authority.
    fused_hits: list[FusedHit] = field(default_factory=list)
    #: Graph relationship triplets (separate evidence kind, own provenance).
    graph_hits: list[GraphHit] = field(default_factory=list)
    #: Real degradation note when a leg failed (never hidden).
    graph_error: str | None = None
    bm25_error: str | None = None


class HybridRetriever:
    """Vector + BM25 + graph retrieval in one call.

    Leg failures degrade individually (recorded, never silent); only a vector
    failure is fatal — without chunks there is no evidence to answer with.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._vector = VectorRetriever(self.settings)
        self._bm25 = BM25Retriever(self.settings)
        self._graph = GraphRetriever(self.settings)

    def retrieve(self, query: str, top_k: int | None = None) -> HybridEvidence:
        top_k = top_k or self.settings.top_k
        # Per-leg fetch depth > top_k: RRF ranks each leg independently, and a
        # chunk found mid-list on BOTH legs can outrank single-leg top hits —
        # truncating each leg to top_k first would drop exactly those chunks
        # (measured 2026-09-09: the PTO accrual chunk was vector-rank 6 +
        # bm25-rank 10; a top_k=8 truncation cut it from the fused list even
        # though it fused to rank 3 when both legs fetched 12). Candidate-pool
        # depth 12 with top_k 5-8 gives the fuser room to promote agreement.
        leg_depth = max(top_k, 12)

        vector_hits = self._vector.retrieve(query, top_k=leg_depth)

        bm25_hits: list[BM25Hit] = []
        bm25_error: str | None = None
        try:
            bm25_hits = self._bm25.retrieve(query, top_k=leg_depth)
        except Exception as exc:  # noqa: BLE001 — degrade loudly, don't fake keyword evidence
            logger.warning("BM25 retrieval failed (%s); continuing without keyword leg", exc)
            bm25_error = str(exc)

        fused_hits = rrf_fuse(vector_hits, bm25_hits)[:top_k]

        graph_hits: list[GraphHit] = []
        graph_error: str | None = None
        try:
            graph_hits = self._graph.retrieve(query, top_k=top_k)
        except Exception as exc:  # noqa: BLE001 — degrade loudly, don't fake graph evidence
            logger.warning("Graph retrieval failed (%s); continuing with chunk evidence only", exc)
            graph_error = str(exc)

        logger.info(
            "Hybrid retrieval: %d vector + %d bm25 → %d fused | %d graph triplets",
            len(vector_hits), len(bm25_hits), len(fused_hits), len(graph_hits),
        )
        return HybridEvidence(
            vector_hits=vector_hits,
            bm25_hits=bm25_hits,
            fused_hits=fused_hits,
            graph_hits=graph_hits,
            graph_error=graph_error,
            bm25_error=bm25_error,
        )