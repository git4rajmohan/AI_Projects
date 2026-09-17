"""Thin operational/read layer over Qdrant (plan.md Phase 4).

This module NEVER embeds documents or writes vectors — it observes and manages
whatever collections the ingestion layer (Cognee) populates:

    health_check, collection_exists, get_collection_info, delete_collection, reset
"""

from __future__ import annotations

from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import Distance

from app.config.settings import Settings, get_settings

#: Default distance metric assumed for collections we don't control
#: (Cognee's Qdrant adapter uses Cosine by default).
DEFAULT_DISTANCE = Distance.COSINE

_client: QdrantClient | None = None


def get_client(settings: Settings | None = None) -> QdrantClient:
    """Shared client (short timeout — this module is for status/ops calls only)."""
    global _client
    if _client is None:
        s = settings or get_settings()
        _client = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None, timeout=10)
    return _client


def reset_client() -> None:
    """Drop the shared client (used after settings changes / in tests)."""
    global _client
    _client = None


def health_check(client: QdrantClient | None = None) -> dict[str, Any]:
    """Real connectivity probe: can we list collections?"""
    try:
        client = client or get_client()
        collections = client.get_collections().collections
        return {"ok": True, "collections": [c.name for c in collections]}
    except Exception as exc:  # noqa: BLE001 — any failure means "down", report why
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def collection_exists(name: str, client: QdrantClient | None = None) -> bool:
    return (client or get_client()).collection_exists(name)


def list_collections(client: QdrantClient | None = None) -> list[str]:
    """Real collection names (read-only; used by reset + status displays)."""
    return health_check(client).get("collections", [])


def get_collection_info(name: str, client: QdrantClient | None = None) -> dict[str, Any] | None:
    """Vector count + embedding dimension for a collection; None if it doesn't exist."""
    client = client or get_client()
    if not client.collection_exists(name):
        return None
    info = client.get_collection(name)
    vectors = info.config.params.vectors
    size = getattr(vectors, "size", None)  # named-vectors collections carry a dict here
    return {
        "name": name,
        "status": str(info.status),
        "points_count": info.points_count or 0,
        "vector_size": size,
    }


def delete_collection(name: str, client: QdrantClient | None = None) -> bool:
    """Delete one collection; False if it was already absent."""
    client = client or get_client()
    if not client.collection_exists(name):
        return False
    client.delete_collection(name)
    return True


def reset(client: QdrantClient | None = None, settings: Settings | None = None) -> bool:
    """Delete the configured application collection (used by scripts/reset_database.py)."""
    s = settings or get_settings()
    return delete_collection(s.qdrant_collection, client)