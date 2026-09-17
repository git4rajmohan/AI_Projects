"""Memory Manager — working memory, long-term memory, and skill memory.

Matches instruction.md section 18 (Memory Architecture).

Memory types:
1. Working Memory — specific to one task, contains intent, plan, agent outputs,
   tool results, intermediate state, decisions, errors. Cleared after task completes.
2. Long-Term Memory — persistent information, database-backed. Survives across
   tasks and sessions. Stores user preferences, learned patterns, past results.
3. Skill Memory — stores reusable workflow definitions. Separate from personal
   user memory. (Handled by the Skill Registry in Phase 5.)

The Memory Manager provides a unified interface for agents and the orchestrator
to store and retrieve memory across all scopes.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Memory scopes
SCOPE_WORKING = "working"
SCOPE_LONG_TERM = "long_term"
SCOPE_SKILL = "skill"


class MemoryEntry:
    """A single memory entry."""

    def __init__(
        self,
        key: str,
        value: Any,
        scope: str = SCOPE_WORKING,
        task_id: str = "",
        agent_id: str = "",
        metadata: dict | None = None,
    ) -> None:
        self.id = str(uuid.uuid4())
        self.key = key
        self.value = value
        self.scope = scope
        self.task_id = task_id
        self.agent_id = agent_id
        self.metadata = metadata or {}
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = self.created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "key": self.key,
            "value": self.value,
            "scope": self.scope,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class MemoryManager:
    """Manages working, long-term, and skill memory.

    Working memory is in-memory (per task, cleared on completion).
    Long-term memory is persisted to disk as JSON files.
    Skill memory is managed by the Skill Registry.

    Usage:
        manager = MemoryManager()
        manager.set("working", "intent", "Analyze sales data", task_id="t1")
        value = manager.get("working", "intent", task_id="t1")
    """

    def __init__(self, storage_dir: str = "data/memory") -> None:
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

        # Working memory: task_id → {key → MemoryEntry}
        self._working: dict[str, dict[str, MemoryEntry]] = {}

        # Long-term memory cache: key → MemoryEntry
        self._long_term_cache: dict[str, MemoryEntry] = {}
        self._long_term_loaded = False

    # --- Working Memory ---

    def set_working(
        self,
        task_id: str,
        key: str,
        value: Any,
        agent_id: str = "",
        metadata: dict | None = None,
    ) -> None:
        """Set a value in working memory for a specific task."""
        if task_id not in self._working:
            self._working[task_id] = {}
        entry = MemoryEntry(
            key=key,
            value=value,
            scope=SCOPE_WORKING,
            task_id=task_id,
            agent_id=agent_id,
            metadata=metadata,
        )
        self._working[task_id][key] = entry
        logger.debug(f"Working memory set: task={task_id}, key={key}")

    def get_working(self, task_id: str, key: str, default: Any = None) -> Any:
        """Get a value from working memory."""
        task_mem = self._working.get(task_id, {})
        entry = task_mem.get(key)
        return entry.value if entry else default

    def get_all_working(self, task_id: str) -> dict[str, Any]:
        """Get all working memory entries for a task."""
        task_mem = self._working.get(task_id, {})
        return {k: v.value for k, v in task_mem.items()}

    def delete_working(self, task_id: str, key: str) -> bool:
        """Delete a key from working memory."""
        task_mem = self._working.get(task_id, {})
        if key in task_mem:
            del task_mem[key]
            return True
        return False

    def clear_working(self, task_id: str) -> None:
        """Clear all working memory for a task (called after task completes)."""
        if task_id in self._working:
            count = len(self._working[task_id])
            del self._working[task_id]
            logger.info(f"Cleared {count} working memory entries for task {task_id}")

    def list_working_keys(self, task_id: str) -> list[str]:
        """List all keys in working memory for a task."""
        return list(self._working.get(task_id, {}).keys())

    # --- Long-Term Memory ---

    def _long_term_path(self) -> Path:
        """Path to the long-term memory JSON file."""
        return self._storage_dir / "long_term.json"

    def _load_long_term(self) -> None:
        """Load long-term memory from disk (lazy, once)."""
        if self._long_term_loaded:
            return

        path = self._long_term_path()
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for entry_data in data:
                    entry = MemoryEntry(
                        key=entry_data["key"],
                        value=entry_data["value"],
                        scope=SCOPE_LONG_TERM,
                        metadata=entry_data.get("metadata", {}),
                    )
                    entry.id = entry_data.get("id", entry.id)
                    self._long_term_cache[entry.key] = entry
                logger.info(f"Loaded {len(self._long_term_cache)} long-term memory entries")
            except Exception as e:
                logger.error(f"Failed to load long-term memory: {e}")

        self._long_term_loaded = True

    def _save_long_term(self) -> None:
        """Persist long-term memory to disk."""
        path = self._long_term_path()
        data = [e.to_dict() for e in self._long_term_cache.values()]
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save long-term memory: {e}")

    def set_long_term(
        self,
        key: str,
        value: Any,
        metadata: dict | None = None,
    ) -> None:
        """Set a value in long-term memory (persisted to disk)."""
        self._load_long_term()

        if key in self._long_term_cache:
            entry = self._long_term_cache[key]
            entry.value = value
            entry.updated_at = datetime.now(timezone.utc)
            if metadata:
                entry.metadata.update(metadata)
        else:
            entry = MemoryEntry(
                key=key,
                value=value,
                scope=SCOPE_LONG_TERM,
                metadata=metadata,
            )
            self._long_term_cache[key] = entry

        self._save_long_term()
        logger.debug(f"Long-term memory set: key={key}")

    def get_long_term(self, key: str, default: Any = None) -> Any:
        """Get a value from long-term memory."""
        self._load_long_term()
        entry = self._long_term_cache.get(key)
        return entry.value if entry else default

    def delete_long_term(self, key: str) -> bool:
        """Delete a key from long-term memory."""
        self._load_long_term()
        if key in self._long_term_cache:
            del self._long_term_cache[key]
            self._save_long_term()
            return True
        return False

    def list_long_term_keys(self) -> list[str]:
        """List all keys in long-term memory."""
        self._load_long_term()
        return list(self._long_term_cache.keys())

    def search_long_term(self, query: str) -> list[dict[str, Any]]:
        """Search long-term memory by keyword (simple substring match).

        Phase 9 future: replace with vector similarity search.
        """
        self._load_long_term()
        results: list[dict[str, Any]] = []
        query_lower = query.lower()

        for entry in self._long_term_cache.values():
            # Search in key and stringified value
            searchable = f"{entry.key} {json.dumps(entry.value, default=str)}".lower()
            if query_lower in searchable:
                results.append(entry.to_dict())

        return results

    # --- Unified Interface ---

    def set(
        self,
        scope: str,
        key: str,
        value: Any,
        task_id: str = "",
        agent_id: str = "",
        metadata: dict | None = None,
    ) -> None:
        """Set a memory value in the specified scope."""
        if scope == SCOPE_WORKING:
            self.set_working(task_id, key, value, agent_id, metadata)
        elif scope == SCOPE_LONG_TERM:
            self.set_long_term(key, value, metadata)
        else:
            raise ValueError(f"Unknown memory scope: {scope}")

    def get(
        self,
        scope: str,
        key: str,
        task_id: str = "",
        default: Any = None,
    ) -> Any:
        """Get a memory value from the specified scope."""
        if scope == SCOPE_WORKING:
            return self.get_working(task_id, key, default)
        elif scope == SCOPE_LONG_TERM:
            return self.get_long_term(key, default)
        else:
            raise ValueError(f"Unknown memory scope: {scope}")


# --- Singleton ---

_memory_manager: MemoryManager | None = None


def get_memory_manager() -> MemoryManager:
    """Get the singleton MemoryManager instance."""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager