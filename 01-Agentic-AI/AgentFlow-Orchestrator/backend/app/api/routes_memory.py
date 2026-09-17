"""API routes for memory management.

GET  /api/memory/long-term — List all long-term memory keys
GET  /api/memory/long-term/{key} — Get a long-term memory value
POST /api/memory/long-term — Set a long-term memory value
DELETE /api/memory/long-term/{key} — Delete a long-term memory value
GET  /api/memory/long-term/search?q=... — Search long-term memory
GET  /api/memory/working/{task_id} — Get all working memory for a task
DELETE /api/memory/working/{task_id} — Clear working memory for a task
"""

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.memory.manager import get_memory_manager

router = APIRouter()
logger = logging.getLogger(__name__)


class SetMemoryRequest(BaseModel):
    """Request to set a memory value."""

    key: str
    value: str  # JSON-serializable value
    metadata: dict = {}


@router.get("/long-term")
async def list_long_term():
    """List all long-term memory keys."""
    manager = get_memory_manager()
    keys = manager.list_long_term_keys()
    return {"keys": keys, "count": len(keys)}


@router.get("/long-term/search")
async def search_long_term(q: str = Query(..., description="Search query")):
    """Search long-term memory by keyword."""
    manager = get_memory_manager()
    results = manager.search_long_term(q)
    return {"results": results, "count": len(results)}


@router.get("/long-term/{key}")
async def get_long_term(key: str):
    """Get a long-term memory value."""
    manager = get_memory_manager()
    value = manager.get_long_term(key)
    if value is None:
        raise HTTPException(status_code=404, detail=f"Key '{key}' not found in long-term memory")
    return {"key": key, "value": value}


@router.post("/long-term")
async def set_long_term(request: SetMemoryRequest):
    """Set a long-term memory value."""
    manager = get_memory_manager()
    manager.set_long_term(request.key, request.value, request.metadata)
    return {"status": "set", "key": request.key}


@router.delete("/long-term/{key}")
async def delete_long_term(key: str):
    """Delete a long-term memory value."""
    manager = get_memory_manager()
    deleted = manager.delete_long_term(key)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Key '{key}' not found")
    return {"status": "deleted", "key": key}


@router.get("/working/{task_id}")
async def get_working(task_id: str):
    """Get all working memory for a task."""
    manager = get_memory_manager()
    memory = manager.get_all_working(task_id)
    return {"task_id": task_id, "memory": memory, "count": len(memory)}


@router.delete("/working/{task_id}")
async def clear_working(task_id: str):
    """Clear all working memory for a task."""
    manager = get_memory_manager()
    manager.clear_working(task_id)
    return {"status": "cleared", "task_id": task_id}