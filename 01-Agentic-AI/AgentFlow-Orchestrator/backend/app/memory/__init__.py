"""Memory module — working, long-term, and skill memory management.

Phase 9: Advanced Features
"""

from app.memory.manager import (
    SCOPE_LONG_TERM,
    SCOPE_SKILL,
    SCOPE_WORKING,
    MemoryEntry,
    MemoryManager,
    get_memory_manager,
)

__all__ = [
    "SCOPE_LONG_TERM",
    "SCOPE_SKILL",
    "SCOPE_WORKING",
    "MemoryEntry",
    "MemoryManager",
    "get_memory_manager",
]