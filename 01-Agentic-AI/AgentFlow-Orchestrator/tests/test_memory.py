"""Tests for the Memory Manager.

Matches instruction.md section 18 (Memory Architecture).
"""

import pytest

from app.memory.manager import (
    SCOPE_LONG_TERM,
    SCOPE_WORKING,
    MemoryManager,
    get_memory_manager,
)


class TestWorkingMemory:
    """Test working memory (per-task, in-memory)."""

    def test_set_and_get(self):
        """Set and get a value in working memory."""
        manager = MemoryManager()
        manager.set_working("task-1", "intent", "Analyze sales data")

        value = manager.get_working("task-1", "intent")
        assert value == "Analyze sales data"

    def test_get_default(self):
        """Getting a non-existent key returns default."""
        manager = MemoryManager()
        value = manager.get_working("task-1", "nonexistent", default="default")
        assert value == "default"

    def test_get_all(self):
        """Get all working memory for a task."""
        manager = MemoryManager()
        manager.set_working("task-2", "key1", "val1")
        manager.set_working("task-2", "key2", "val2")

        all_mem = manager.get_all_working("task-2")
        assert all_mem["key1"] == "val1"
        assert all_mem["key2"] == "val2"

    def test_delete(self):
        """Delete a key from working memory."""
        manager = MemoryManager()
        manager.set_working("task-3", "key", "val")

        deleted = manager.delete_working("task-3", "key")
        assert deleted
        assert manager.get_working("task-3", "key") is None

    def test_clear(self):
        """Clear all working memory for a task."""
        manager = MemoryManager()
        manager.set_working("task-4", "key1", "val1")
        manager.set_working("task-4", "key2", "val2")

        manager.clear_working("task-4")
        assert manager.get_all_working("task-4") == {}

    def test_list_keys(self):
        """List all keys in working memory."""
        manager = MemoryManager()
        manager.set_working("task-5", "a", 1)
        manager.set_working("task-5", "b", 2)

        keys = manager.list_working_keys("task-5")
        assert set(keys) == {"a", "b"}

    def test_isolation_between_tasks(self):
        """Working memory is isolated between tasks."""
        manager = MemoryManager()
        manager.set_working("task-a", "key", "val-a")
        manager.set_working("task-b", "key", "val-b")

        assert manager.get_working("task-a", "key") == "val-a"
        assert manager.get_working("task-b", "key") == "val-b"


class TestLongTermMemory:
    """Test long-term memory (persisted to disk)."""

    def test_set_and_get(self):
        """Set and get a value in long-term memory."""
        manager = MemoryManager()
        manager.set_long_term("test-key-1", "test-value")

        value = manager.get_long_term("test-key-1")
        assert value == "test-value"

    def test_get_default(self):
        """Getting a non-existent key returns default."""
        manager = MemoryManager()
        value = manager.get_long_term("nonexistent-key", default="default")
        assert value == "default"

    def test_delete(self):
        """Delete a key from long-term memory."""
        manager = MemoryManager()
        manager.set_long_term("test-key-2", "val")

        deleted = manager.delete_long_term("test-key-2")
        assert deleted
        assert manager.get_long_term("test-key-2") is None

    def test_list_keys(self):
        """List all keys in long-term memory."""
        manager = MemoryManager()
        manager.set_long_term("test-list-1", "val1")
        manager.set_long_term("test-list-2", "val2")

        keys = manager.list_long_term_keys()
        assert "test-list-1" in keys
        assert "test-list-2" in keys

    def test_search(self):
        """Search long-term memory by keyword."""
        manager = MemoryManager()
        manager.set_long_term("test-search-key", "This contains the word sales")

        results = manager.search_long_term("sales")
        assert len(results) >= 1
        assert any(r["key"] == "test-search-key" for r in results)

    def test_update_existing(self):
        """Updating an existing key overwrites the value."""
        manager = MemoryManager()
        manager.set_long_term("test-update", "original")
        manager.set_long_term("test-update", "updated")

        assert manager.get_long_term("test-update") == "updated"


class TestUnifiedInterface:
    """Test the unified set/get interface."""

    def test_set_get_working(self):
        """Unified interface works for working memory."""
        manager = MemoryManager()
        manager.set(SCOPE_WORKING, "key", "val", task_id="task-u1")

        assert manager.get(SCOPE_WORKING, "key", task_id="task-u1") == "val"

    def test_set_get_long_term(self):
        """Unified interface works for long-term memory."""
        manager = MemoryManager()
        manager.set(SCOPE_LONG_TERM, "key-u2", "val-u2")

        assert manager.get(SCOPE_LONG_TERM, "key-u2") == "val-u2"

    def test_invalid_scope_raises(self):
        """Invalid scope raises ValueError."""
        manager = MemoryManager()
        with pytest.raises(ValueError):
            manager.set("invalid_scope", "key", "val")


class TestSingleton:
    """Test the singleton pattern."""

    def test_get_memory_manager_singleton(self):
        """get_memory_manager returns the same instance."""
        m1 = get_memory_manager()
        m2 = get_memory_manager()
        assert m1 is m2