"""Tests for the execution state manager.

Matches instruction.md section 16 (Execution State).
"""

import pytest

from app.orchestrator.state import ExecutionState, StateManager, get_state_manager


class TestExecutionState:
    """Test the in-memory ExecutionState object."""

    def test_initial_state(self):
        """New execution state starts as pending."""
        state = ExecutionState(
            execution_id="exec-1",
            task_id="task-1",
            plan_id="plan-1",
        )
        assert state.status == "pending"
        assert state.current_nodes == []
        assert state.completed_nodes == []
        assert state.failed_nodes == []
        assert state.outputs == {}

    def test_mark_started(self):
        """mark_started sets status to running."""
        state = ExecutionState("e1", "t1", "p1")
        state.mark_started()
        assert state.status == "running"
        assert state.started_at is not None

    def test_mark_completed(self):
        """mark_completed sets status to completed."""
        state = ExecutionState("e1", "t1", "p1")
        state.mark_started()
        state.mark_completed()
        assert state.status == "completed"
        assert state.completed_at is not None

    def test_mark_failed(self):
        """mark_failed sets status and error."""
        state = ExecutionState("e1", "t1", "p1")
        state.mark_failed("Something went wrong")
        assert state.status == "failed"
        assert state.error == "Something went wrong"

    def test_mark_cancelled(self):
        """mark_cancelled sets status to cancelled."""
        state = ExecutionState("e1", "t1", "p1")
        state.mark_cancelled()
        assert state.status == "cancelled"

    def test_add_output(self):
        """add_output records output and marks agent completed."""
        state = ExecutionState("e1", "t1", "p1")
        state.mark_node_started("agent_1")
        state.add_output("agent_1", {"result": "done"})

        assert state.outputs["agent_1"] == {"result": "done"}
        assert "agent_1" in state.completed_nodes
        assert "agent_1" not in state.current_nodes

    def test_mark_failed_node(self):
        """mark_failed_node records the failed agent."""
        state = ExecutionState("e1", "t1", "p1")
        state.mark_node_started("agent_1")
        state.mark_failed_node("agent_1")

        assert "agent_1" in state.failed_nodes
        assert "agent_1" not in state.current_nodes

    def test_mark_node_started(self):
        """mark_node_started adds to current_nodes."""
        state = ExecutionState("e1", "t1", "p1")
        state.mark_node_started("agent_1")
        assert "agent_1" in state.current_nodes

    def test_to_dict(self):
        """to_dict serializes state correctly."""
        state = ExecutionState("e1", "t1", "p1")
        state.mark_node_started("a1")
        state.add_output("a1", {"x": 1})
        state.mark_node_started("a2")

        d = state.to_dict()
        assert "a1" in d["completed_nodes"]
        assert "a2" in d["current_nodes"]
        assert d["outputs"]["a1"] == {"x": 1}


class TestStateManager:
    """Test the StateManager DB operations."""

    @pytest.mark.asyncio
    async def test_create_and_load_execution(self):
        """Create an execution, then load it back from DB."""
        manager = StateManager()

        # Create
        state = await manager.create_execution(
            task_id="test-task-1",
            plan_id="test-plan-1",
        )
        assert state.status == "pending"
        exec_id = state.execution_id

        # Load
        loaded = await manager.load_state(exec_id)
        assert loaded is not None
        assert loaded.task_id == "test-task-1"
        assert loaded.plan_id == "test-plan-1"
        assert loaded.status == "pending"

    @pytest.mark.asyncio
    async def test_save_and_load_state(self):
        """Save state changes and load them back."""
        manager = StateManager()

        state = await manager.create_execution(
            task_id="test-task-2",
            plan_id="test-plan-2",
        )

        # Modify and save
        state.mark_started()
        state.mark_node_started("agent_1")
        state.add_output("agent_1", {"result": "hello"})
        state.total_tool_calls = 3
        await manager.save_state(state)

        # Load and verify
        loaded = await manager.load_state(state.execution_id)
        assert loaded is not None
        assert loaded.status == "running"
        assert "agent_1" in loaded.completed_nodes
        assert loaded.outputs["agent_1"] == {"result": "hello"}
        assert loaded.total_tool_calls == 3

    @pytest.mark.asyncio
    async def test_load_nonexistent(self):
        """Loading a non-existent execution returns None."""
        manager = StateManager()
        loaded = await manager.load_state("nonexistent-id")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_get_execution(self):
        """get_execution returns the execution dict."""
        manager = StateManager()

        state = await manager.create_execution(
            task_id="test-task-3",
            plan_id="test-plan-3",
        )

        result = await manager.get_execution(state.execution_id)
        assert result is not None
        assert result["task_id"] == "test-task-3"
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_execution_nonexistent(self):
        """get_execution returns None for non-existent ID."""
        manager = StateManager()
        result = await manager.get_execution("nonexistent-id")
        assert result is None