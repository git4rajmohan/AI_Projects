"""Phase 4 tests against the real local Qdrant instance.

Collection lifecycle is exercised with a throwaway test collection created via
raw qdrant-client (the manager itself never creates/inserts — that's the point
of the thin layer). Skips cleanly when Qdrant isn't running.
"""

from __future__ import annotations

import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from app.vectorstore import qdrant_manager
from app.vectorstore.qdrant_manager import (
    collection_exists,
    delete_collection,
    get_collection_info,
    health_check,
    list_collections,
)


def _live_client() -> QdrantClient | None:
    """Real client if Qdrant is up, else None (tests skip)."""
    probe = QdrantClient(url="http://localhost:6333", timeout=3)
    try:
        probe.get_collections()
        return probe
    except Exception:
        return None


@pytest.fixture
def live() -> QdrantClient:
    client = _live_client()
    if client is None:
        pytest.skip("local Qdrant not running")
    return client


def test_health_check(live: QdrantClient) -> None:
    result = health_check(live)
    assert result["ok"] is True
    assert "collections" in result


def test_list_collections(live: QdrantClient) -> None:
    """Phase 12: real names list; a created collection appears in it."""
    name = "_phase12_list_collection_"
    try:
        assert name not in list_collections(live)
        live.create_collection(name, vectors_config=VectorParams(size=8, distance=Distance.COSINE))
        assert name in list_collections(live)
    finally:
        delete_collection(name, live)


def test_collection_lifecycle(live: QdrantClient) -> None:
    name = "_phase4_test_collection_"
    try:
        # Arrange: empty collection via raw client (no vectors inserted).
        live.create_collection(name, vectors_config=VectorParams(size=8, distance=Distance.COSINE))

        assert collection_exists(name, live) is True

        info = get_collection_info(name, live)
        assert info is not None
        assert info["points_count"] == 0
        assert info["vector_size"] == 8

        # Missing collection reports None, not an exception.
        assert get_collection_info("_phase4_missing_", live) is None
    finally:
        assert delete_collection(name, live) is True
        assert collection_exists(name, live) is False
        assert delete_collection(name, live) is False  # second delete: absent -> False