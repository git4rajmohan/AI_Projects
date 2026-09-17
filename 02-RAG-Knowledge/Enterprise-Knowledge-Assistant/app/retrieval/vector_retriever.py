"""VectorRetriever — semantic search over the Cognee-populated Qdrant collection.

Phase 7 decision (instructions.md §23): Cognee's Qdrant payloads carry ``text``
plus internal fields but NO filename metadata, and LlamaIndex's
``QdrantVectorStore`` expects its own ``_node_content`` payload schema. Direct
collection sharing is therefore NOT compatible -> Design C (adapter layer):

    LlamaIndex Retriever -> this adapter -> Cognee's Qdrant collection

This module is a READ layer only — it never embeds or inserts (that's Cognee's
job, enforced in plan.md). It queries the collection Cognee populated during
Phase 5/6 using the same embedding model (local ``nomic-embed-text``, 768-dim).

Citations: Cognee stores no filename on chunks, so we resolve provenance from
the ingest ledger (``data/metadata/ingested.json`` hash->filename), and record
that limitation in the returned metadata instead of inventing a source.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import requests

from app.config.settings import Settings, get_settings
from app.vectorstore import qdrant_manager

logger = logging.getLogger(__name__)

#: Cognee names its collections after the model type it stores:
#: ``DocumentChunk_text`` holds the text chunks we retrieve.
CHUNK_COLLECTION = "DocumentChunk_text"
#: Cognee's named-vector key inside each collection (verified Phase 5).
COGNEE_VECTOR_NAME = "text"


@dataclass
class VectorHit:
    """One retrieved chunk, per instructions.md §24 (document/chunk/score/metadata/source)."""

    chunk_id: str
    text: str
    score: float
    document: str
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorRetriever:
    """Query Cognee's Qdrant collection with a local-dameon-embedded query."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._embed_url = f"{self.settings.local_base_url.rstrip('/')}/api/embed"

    # -- embedding -------------------------------------------------------- #
    def _embed_query(self, query: str) -> list[float]:
        """Embed via the LOCAL daemon's native /api/embed (same model as ingest)."""
        resp = requests.post(
            self._embed_url,
            json={"model": self.settings.embed_model, "input": query},
            timeout=120,
        )
        resp.raise_for_status()
        payload = resp.json()
        embeddings = payload.get("embeddings") or [payload.get("embedding")]
        if not embeddings or not embeddings[0]:
            raise RuntimeError(f"Query embedding failed for {self.settings.embed_model!r}")
        return embeddings[0]

    # -- provenance ------------------------------------------------------- #
    def _load_document_names(self) -> dict[str, str]:
        """chunk-id -> document stem, resolved from the Cognee graph.

        Graph provenance is REAL: ``DocumentChunk --is_part_of--> TextDocument``
        with TextDocument.name = document stem (verified Phase 7). Chunks not
        present in the map (e.g. graph unavailable) fall back to 'unknown'
        rather than a guessed filename.
        """
        try:
            from app.knowledge.cognee_manager import CognifyManager

            return CognifyManager(self.settings).get_chunk_document_map()
        except Exception as exc:  # noqa: BLE001 — report, don't fake
            logger.warning("Graph provenance unavailable (%s); citations will say 'unknown'", exc)
            return {}

    # -- retrieval -------------------------------------------------------- #
    def retrieve(self, query: str, top_k: int | None = None) -> list[VectorHit]:
        """Semantic search; returns up to ``top_k`` hits with real scores."""
        top_k = top_k or self.settings.top_k
        client = qdrant_manager.get_client(self.settings)
        if not qdrant_manager.collection_exists(CHUNK_COLLECTION, client):
            raise RuntimeError(
                f"Collection {CHUNK_COLLECTION!r} does not exist — ingest documents first."
            )
        vector = self._embed_query(query)
        results = client.query_points(
            CHUNK_COLLECTION,
            query=vector,
            using=COGNEE_VECTOR_NAME,
            limit=top_k,
            with_payload=True,
        )
        names = self._load_document_names()
        hits: list[VectorHit] = []
        for point in results.points:
            payload = point.payload or {}
            text = payload.get("text", "")
            # Graph provenance or an honest 'unknown' — never a guessed name.
            doc_stem = names.get(str(point.id))
            source = f"{doc_stem}.pdf" if doc_stem else "unknown (provenance not resolvable)"
            hits.append(
                VectorHit(
                    chunk_id=str(point.id),
                    text=text,
                    score=float(point.score) if point.score is not None else 0.0,
                    document=source,
                    metadata={
                        "collection": CHUNK_COLLECTION,
                        "type": payload.get("type"),
                        "created_at": payload.get("created_at"),
                    },
                )
            )
        logger.info("Vector retrieval: %d hits for query (%d chars)", len(hits), len(query))
        return hits