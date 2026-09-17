"""BM25Retriever — keyword retrieval over the Cognee chunks (§8, item 7).

The alternateplan.md definition of hybrid retrieval is vector + BM25; the
graph leg is this project's differentiator on top. BM25 gives exact-terminology
matching that embeddings miss (policy IDs like "ACME-HR-002", statutory
phrases, rare terms).

Design constraints honored:

  * Read-only: chunks are scrolled from the Qdrant collection Cognee populated
    (``DocumentChunk_text``). No re-chunking, no re-embedding, no writes — the
    single-ingestion-path rule stays intact.
  * The index is built ONCE per process (131 chunks), then reused; ``rebuild()``
    re-scrolls after new ingestion without restarting the app.
  * Scores are BM25 magnitudes (unbounded, corpus-dependent) — consumers that
    need comparable scores across retrievers must use RRF (item 8), which this
    module deliberately does NOT do. Fusion lives in hybrid_retriever.
  * Simple regex tokenizer; no extra NLP dependency.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.config.settings import Settings, get_settings
from app.retrieval.vector_retriever import CHUNK_COLLECTION, COGNEE_VECTOR_NAME
from app.vectorstore import qdrant_manager

logger = logging.getLogger(__name__)

#: Scroll page size when pulling the full chunk corpus from Qdrant.
_SCROLL_SIZE = 256

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens — deterministic, dependency-free."""
    return _TOKEN_RE.findall(text.lower())


@dataclass
class BM25Hit:
    """One keyword-retrieval hit (same shape as VectorHit for downstream reuse)."""

    chunk_id: str
    text: str
    score: float
    document: str
    metadata: dict[str, Any] = field(default_factory=dict)


class BM25Retriever:
    """BM25 keyword search over the chunk texts already in Qdrant.

    Pure in-memory: all chunk texts are loaded once and scored with
    ``rank_bm25.BM25Okapi``. For a 131-chunk corpus this is instant and needs
    no extra service.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._docs: list[dict[str, Any]] = []  # {"chunk_id", "text", "doc"}
        self._bm25: Any = None
        self._corpus_tokens: list[list[str]] = []

    # -- index ------------------------------------------------------------- #
    def build(self) -> int:
        """Scroll all chunks from Qdrant and build the BM25 index. Returns size."""
        client = qdrant_manager.get_client(self.settings)
        if not qdrant_manager.collection_exists(CHUNK_COLLECTION, client):
            raise RuntimeError(
                f"Collection {CHUNK_COLLECTION!r} does not exist — ingest documents first."
            )
        # Graph provenance (same source VectorRetriever uses) for real filenames.
        names: dict[str, str] = {}
        try:
            from app.knowledge.cognee_manager import CognifyManager

            names = CognifyManager(self.settings).get_chunk_document_map()
        except Exception as exc:  # noqa: BLE001 — citations degrade, retrieval doesn't
            logger.warning("Graph provenance unavailable (%s); BM25 citations will say 'unknown'", exc)

        docs: list[dict[str, Any]] = []
        offset = None
        while True:
            points, offset = client.scroll(
                CHUNK_COLLECTION,
                with_payload=True,
                with_vectors=False,
                limit=_SCROLL_SIZE,
                offset=offset,
            )
            for point in points:
                payload = point.payload or {}
                text = payload.get("text", "")
                if not text:
                    continue
                chunk_id = str(point.id)
                stem = names.get(chunk_id)
                docs.append(
                    {
                        "chunk_id": chunk_id,
                        "text": text,
                        "doc": f"{stem}.pdf" if stem else "unknown (provenance not resolvable)",
                        "metadata": {
                            "collection": CHUNK_COLLECTION,
                            "type": payload.get("type"),
                            "created_at": payload.get("created_at"),
                        },
                    }
                )
            if offset is None:
                break

        self._docs = docs
        self._corpus_tokens = [tokenize(d["text"]) for d in docs]
        # BM25Okapi with empty docs would raise; keep _bm25 None so retrieve() errs clearly.
        from rank_bm25 import BM25Okapi

        self._bm25 = BM25Okapi(self._corpus_tokens) if docs else None
        logger.info("BM25 index built: %d chunks", len(docs))
        return len(docs)

    def rebuild(self) -> int:
        """Re-scroll Qdrant (after ingestion) and rebuild the index."""
        return self.build()

    @property
    def size(self) -> int:
        return len(self._docs)

    # -- retrieval --------------------------------------------------------- #
    def retrieve(self, query: str, top_k: int | None = None) -> list[BM25Hit]:
        """Keyword search; returns up to ``top_k`` hits, best first."""
        if self._bm25 is None:
            self.build()
        top_k = top_k or self.settings.top_k
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(enumerate(scores), key=lambda pair: pair[1], reverse=True)[:top_k]
        hits: list[BM25Hit] = []
        for idx, score in ranked:
            if score <= 0.0:
                continue  # no term overlap — not a keyword hit at all
            doc = self._docs[idx]
            hits.append(
                BM25Hit(
                    chunk_id=doc["chunk_id"],
                    text=doc["text"],
                    score=float(score),
                    document=doc["doc"],
                    metadata=doc["metadata"],
                )
            )
        logger.info("BM25 retrieval: %d hits for query (%d chars)", len(hits), len(query))
        return hits

    def text_for(self, chunk_id: str) -> str | None:
        """Chunk text by ID — used by fusion to dedupe against vector hits."""
        for doc in self._docs:
            if doc["chunk_id"] == chunk_id:
                return doc["text"]
        return None