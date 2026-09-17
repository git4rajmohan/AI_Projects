"""GraphRetriever — relationship evidence from the Cognee knowledge graph.

Phase 9 (instructions.md §8 Stage 2): Question → Cognee → Entities →
Relationships → relevant graph evidence.

Implementation verified against the installed pair cognee==1.4.2 + the Ladybug
graph backend (do not trust older tutorials):

  * ``cognee.search(SearchType.GRAPH_COMPLETION, ...)`` runs an LLM completion
    over graph context — useful for a chat answer, but NOT for evidence fusion,
    because it returns a synthesized string rather than the underlying triplets.
  * The retrieval primitive underneath it is
    ``cognee.modules.retrieval.utils.brute_force_triplet_search``:
    query → embedding → vector search over graph node/edge collections →
    ID-filtered graph projection → ranked ``Edge`` objects. We call it directly
    (inside the per-dataset database context Cognee requires) so the app gets
    the REAL triplets as evidence — no second LLM call, no duplicated knowledge
    extraction (single-authoritative-pipeline rule from plan.md).
  * Edge shape (verified live): ``edge.attributes["relationship_name"]``,
    ``edge.node1.attributes["name"|"description"|"type"]``,
    ``edge.node2.attributes[...]``. Distance comes back as
    ``attributes["vector_distance"]`` on both nodes and edge.

Provenance: graph triplets name entities, not source documents. Rather than
guessing a document for each triplet, GraphRetriever reports what the graph
actually stores (entity names/types/relationship) and marks graph evidence as
``document="knowledge graph"`` — citations to real filenames remain the
VectorRetriever's job (its chunk→document map is graph-derived and REAL).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass
class GraphHit:
    """One relationship triplet, per instructions.md §24 (entities/relationship/evidence)."""

    subject: str
    subject_type: str
    relationship: str
    object: str
    object_type: str
    subject_description: str = ""
    object_description: str = ""
    distance: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_text(self) -> str:
        """Human-readable triplet used in LLM context blocks."""
        parts = [f"{self.subject} ({self.subject_type})"]
        if self.subject_description:
            parts.append(f"- subject: {self.subject_description}")
        parts.append(
            f"--[{self.relationship}]--> {self.object} ({self.object_type})"
        )
        if self.object_description:
            parts.append(f"- object: {self.object_description}")
        return "\n".join(parts)


def _node_field(node: Any, key: str) -> str:
    """Safely read a node attribute as a short string (Cognee nodes are dicts)."""
    value = node.attributes.get(key)
    if value is None:
        return ""
    return str(value).replace("\n", " ")[:500]


class GraphRetriever:
    """Retrieve relationship triplets from Cognee's knowledge graph."""

    #: Evidence from the graph has no per-triplet document attribution; we say
    #: so instead of inventing sources.
    SOURCE_LABEL = "knowledge graph"

    def __init__(self, settings: Settings | None = None, top_k: int | None = None) -> None:
        self.settings = settings or get_settings()
        self.top_k = top_k or self.settings.top_k

    def retrieve(self, query: str, top_k: int | None = None) -> list[GraphHit]:
        """Ranked relationship triplets for ``query`` (empty list when none match).

        Raises RuntimeError when the graph isn't ingestible/available — callers
        see the real problem instead of silent emptiness.
        """
        import asyncio

        return asyncio.run(self._retrieve_async(query, top_k or self.top_k))

    async def _retrieve_async(self, query: str, top_k: int) -> list[GraphHit]:
        # configure() FIRST — it sets SYSTEM_ROOT_DIRECTORY before cognee is
        # ever imported in this process. Importing the cognee modules below
        # before configure() caches site-packages storage paths in cognee's
        # config singletons and every graph read then fails with
        # "sqlite3.OperationalError: unable to open database file".
        from app.knowledge.cognee_manager import configure

        configure(self.settings)  # idempotent

        from cognee.context_global_variables import set_database_global_context_variables
        from cognee.modules.data.methods.get_datasets import get_datasets
        from cognee.modules.retrieval.utils.brute_force_triplet_search import (
            brute_force_triplet_search,
        )
        from cognee.modules.users.methods import get_default_user

        user = await get_default_user()
        datasets = await get_datasets(user.id)
        dataset = next((d for d in datasets if d.name == "main_dataset"), None)
        if dataset is None:
            raise RuntimeError("Cognee dataset 'main_dataset' not found — ingest documents first.")

        async with set_database_global_context_variables(dataset.id, user.id):
            edges = await brute_force_triplet_search(query, top_k=top_k)

        hits: list[GraphHit] = []
        for edge in edges or []:
            rel = edge.attributes.get("relationship_name") or "related_to"
            # vector_distance arrives as a per-dimension list (verified live:
            # [0.1097...] for a 1-dim projection) — take the first element.
            raw_distance = edge.attributes.get("vector_distance")
            if isinstance(raw_distance, (list, tuple)):
                raw_distance = raw_distance[0] if raw_distance else None
            distance = raw_distance
            hits.append(
                GraphHit(
                    subject=_node_field(edge.node1, "name") or str(edge.node1.id),
                    subject_type=_node_field(edge.node1, "type") or "Entity",
                    relationship=str(rel),
                    object=_node_field(edge.node2, "name") or str(edge.node2.id),
                    object_type=_node_field(edge.node2, "type") or "Entity",
                    subject_description=_node_field(edge.node1, "description"),
                    object_description=_node_field(edge.node2, "description"),
                    distance=float(distance) if distance is not None else None,
                    metadata={"source": self.SOURCE_LABEL},
                )
            )
        logger.info("Graph retrieval: %d triplets for query (%d chars)", len(hits), len(query))
        return hits