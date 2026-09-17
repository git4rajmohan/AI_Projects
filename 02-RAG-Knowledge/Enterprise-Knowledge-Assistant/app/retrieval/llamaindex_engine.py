"""LlamaIndex orchestration engine (plan.md Phase 7).

Wires the selected LLMProvider's LLM + embedding model into a LlamaIndex query
engine. Retrieval goes through :class:`HybridRetriever` (Phase 10: VectorRetriever
chunks + GraphRetriever triplets; ``strategy="vector"`` for chunks only), because
Cognee's Qdrant payload schema is not LlamaIndex-native, so we don't pretend
``QdrantVectorStore`` can read it directly.

This module contains ZERO local-vs-cloud logic — the provider is whatever
``ollama_manager`` returns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.config.settings import Settings, get_settings
from app.llm.ollama_manager import get_llm_manager
from app.retrieval.bm25_retriever import BM25Hit
from app.retrieval.evidence_gate import REFUSAL_MESSAGE, EvidenceGate
from app.retrieval.fusion import FusedHit
from app.retrieval.graph_retriever import GraphHit, GraphRetriever
from app.retrieval.hybrid_retriever import HybridEvidence, HybridRetriever
from app.retrieval.vector_retriever import VectorHit, VectorRetriever

logger = logging.getLogger(__name__)

#: instructions.md §25 — grounded system prompt, verbatim.
GROUNDED_PROMPT = """\
Answer the user's question using only the provided enterprise
knowledge context.

If the context does not contain enough information to answer,
say that the information could not be found in the available
documents.

Do not invent facts, policies, numbers, dates, sources, or page
numbers.

Preserve exact numbers and dates from the evidence.

When multiple documents provide evidence, distinguish them clearly.

Provide source citations for claims supported by retrieved evidence.
"""


@dataclass
class Citation:
    """instructions.md §27 — filename always; page only when real metadata has one.

    Built exclusively from retrieved nodes; never from the LLM's output.
    """

    document: str
    page: int | None = None


@dataclass
class RetrievalResult:
    """Full answer package: grounded response + the evidence behind it."""

    answer: str
    vector_hits: list[VectorHit] = field(default_factory=list)
    #: Pure keyword ranking (item 7 observability; empty under "vector" strategy).
    bm25_hits: list[BM25Hit] = field(default_factory=list)
    #: RRF-fused chunk ranking (item 8) — the order the LLM saw context in.
    fused_hits: list[FusedHit] = field(default_factory=list)
    graph_hits: list[GraphHit] = field(default_factory=list)
    query: str = ""
    #: Final prompt context (§31 debug panel); empty when recorded nowhere else.
    context: str = ""
    #: Real degradation note when the graph leg failed (from HybridEvidence).
    graph_error: str | None = None
    #: Real degradation note when the BM25 leg failed (item 8).
    bm25_error: str | None = None
    #: Set when the pre-LLM evidence gate refused to generate (item 10).
    #: Non-empty means the LLM was never called for this query.
    refusal_reason: str | None = None
    #: True when the evidence gate refused this query.
    refused: bool = False

    @property
    def sources(self) -> list[str]:
        """Distinct source names from retrieved evidence (never LLM-derived)."""
        return [c.document for c in self.citations]

    @property
    def citations(self) -> list[Citation]:
        """One Citation per distinct document, from real node metadata only."""
        seen: dict[str, Citation] = {}
        for hit in self.vector_hits:
            seen.setdefault(hit.document, Citation(document=hit.document, page=hit.metadata.get("page")))
        return list(seen.values())


class LlamaIndexEngine:
    """Wires provider LLM + VectorRetriever into an answer pipeline."""

    def __init__(self, settings: Settings | None = None, strategy: str = "hybrid") -> None:
        self.settings = settings or get_settings()
        # "hybrid" (default) fuses vector + graph evidence; "vector" is chunks only.
        self.retriever: Any = (
            HybridRetriever(self.settings) if strategy == "hybrid" else VectorRetriever(self.settings)
        )
        self._llm: Any = None
        #: Enforcement gate (§11): refuse before the LLM when evidence is thin.
        self.gate = EvidenceGate(self.settings)

    def _get_llm(self) -> Any:
        if self._llm is None:
            self._llm = get_llm_manager(self.settings).get_llm()
        return self._llm

    def _build_context(
        self,
        chunk_hits: list[VectorHit] | list[FusedHit],
        graph_hits: list[GraphHit],
    ) -> str:
        """Assemble numbered evidence blocks (chunks + graph triplets) for the prompt.

        ``chunk_hits`` are FusedHit (hybrid strategy — RRF order) or VectorHit
        (vector-only strategy). Both carry text+document; FusedHit additionally
        notes which legs contributed, surfaced in debug output via metadata.
        """
        if not chunk_hits and not graph_hits:
            return "No relevant context was retrieved."
        blocks = [
            f"[{i + 1}] {hit.text}\n(source: {hit.document})" for i, hit in enumerate(chunk_hits)
        ]
        blocks += [
            f"[G{i + 1}] {hit.to_text()}\n(source: {GraphRetriever.SOURCE_LABEL})"
            for i, hit in enumerate(graph_hits)
        ]
        return "\n\n".join(blocks)

    def answer(self, query: str, top_k: int | None = None) -> RetrievalResult:
        """Retrieve evidence, then synthesize a grounded answer with the LLM.

        Enforcement (§11): when retrieved evidence doesn't clear the calibrated
        sufficiency bar, return the standard refusal WITHOUT calling the LLM —
        grounding by construction, not by prompt instruction.
        """
        evidence = self.retriever.retrieve(query, top_k=top_k)
        if not isinstance(evidence, HybridEvidence):  # "vector" strategy returns a plain list
            evidence = HybridEvidence(vector_hits=evidence)

        # ---- Enforcement gate: refuse BEFORE the LLM ---------------------- #
        best_score = max((h.score for h in evidence.vector_hits), default=None)
        decision = self.gate.check(best_score)
        if not decision.allowed:
            logger.info(
                "Evidence gate refused (best=%.3f < %.3f): %s",
                decision.best_score,
                decision.threshold,
                decision.reason,
            )
            return RetrievalResult(
                answer=REFUSAL_MESSAGE,
                vector_hits=evidence.vector_hits,
                bm25_hits=getattr(evidence, "bm25_hits", []),
                fused_hits=getattr(evidence, "fused_hits", []),
                graph_hits=evidence.graph_hits,
                query=query,
                context="",
                graph_error=getattr(evidence, "graph_error", None),
                bm25_error=getattr(evidence, "bm25_error", None),
                refusal_reason=decision.reason,
                refused=True,
            )

        # Hybrid strategy orders context by RRF fusion; vector-only by cosine.
        chunk_hits: list[Any] = (
            list(evidence.fused_hits) if evidence.fused_hits else list(evidence.vector_hits)
        )
        context = self._build_context(chunk_hits, evidence.graph_hits)
        prompt = (
            f"{GROUNDED_PROMPT}\n\n"
            f"=== ENTERPRISE KNOWLEDGE CONTEXT ===\n{context}\n"
            f"=== END CONTEXT ===\n\n"
            f"Question: {query}\n"
            f"Answer (cite sources as [1], [2] ... where supported):"
        )
        logger.info("LLM generation started (query: %d chars, context: %d chars)", len(query), len(context))
        response = self._get_llm().complete(prompt)
        answer = str(response).strip()
        logger.info("LLM generation completed (%d chars)", len(answer))
        return RetrievalResult(
            answer=answer,
            vector_hits=evidence.vector_hits,
            bm25_hits=getattr(evidence, "bm25_hits", []),
            fused_hits=getattr(evidence, "fused_hits", []),
            graph_hits=evidence.graph_hits,
            query=query,
            context=context,
            graph_error=getattr(evidence, "graph_error", None),
            bm25_error=getattr(evidence, "bm25_error", None),
        )