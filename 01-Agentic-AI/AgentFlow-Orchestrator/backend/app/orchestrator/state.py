"""Execution state manager — persists execution state to the database.

Matches instruction.md section 16 (Execution State).

State includes:
- current_nodes: agents currently running
- completed_nodes: agents that finished successfully
- failed_nodes: agents that failed
- outputs: agent outputs keyed by agent_id
- events: event count

Critical state must not exist only in process memory.
Execution should be recoverable after application restart.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import database
from app.models.execution import ExecutionModel

logger = logging.getLogger(__name__)


class ExecutionState:
    """In-memory representation of execution state, synced to DB."""

    def __init__(
        self,
        execution_id: str,
        task_id: str,
        plan_id: str,
    ) -> None:
        self.execution_id = execution_id
        self.task_id = task_id
        self.plan_id = plan_id

        self.status: str = "pending"
        self.current_nodes: list[str] = []
        self.completed_nodes: list[str] = []
        self.failed_nodes: list[str] = []
        self.outputs: dict[str, Any] = {}
        self.total_tool_calls: int = 0
        self.total_cost: float = 0.0
        self.result: dict[str, Any] | None = None
        self.error: str | None = None
        self.started_at: datetime | None = None
        self.completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize state to a dict for JSON storage."""
        return {
            "current_nodes": self.current_nodes,
            "completed_nodes": self.completed_nodes,
            "failed_nodes": self.failed_nodes,
            "outputs": self.outputs,
        }

    def mark_started(self) -> None:
        self.status = "running"
        self.started_at = datetime.now(timezone.utc)

    def mark_completed(self) -> None:
        self.status = "completed"
        self.completed_at = datetime.now(timezone.utc)

    def mark_failed(self, error: str) -> None:
        self.status = "failed"
        self.error = error
        self.completed_at = datetime.now(timezone.utc)

    def mark_cancelled(self) -> None:
        self.status = "cancelled"
        self.completed_at = datetime.now(timezone.utc)

    def mark_paused(self) -> None:
        self.status = "paused"

    def add_output(self, agent_id: str, output: dict[str, Any]) -> None:
        """Record an agent's output."""
        self.outputs[agent_id] = output
        if agent_id not in self.completed_nodes:
            self.completed_nodes.append(agent_id)
        if agent_id in self.current_nodes:
            self.current_nodes.remove(agent_id)

    def mark_failed_node(self, agent_id: str) -> None:
        """Mark an agent as failed."""
        if agent_id not in self.failed_nodes:
            self.failed_nodes.append(agent_id)
        if agent_id in self.current_nodes:
            self.current_nodes.remove(agent_id)

    def mark_node_started(self, agent_id: str) -> None:
        """Mark an agent as currently running."""
        if agent_id not in self.current_nodes:
            self.current_nodes.append(agent_id)


class StateManager:
    """Persists execution state to the database.

    Ensures state survives application restarts.
    """

    async def create_execution(
        self,
        task_id: str,
        plan_id: str,
    ) -> ExecutionState:
        """Create a new execution record in the database.

        Args:
            task_id: The parent task ID.
            plan_id: The plan being executed.

        Returns:
            An ExecutionState object for tracking the execution.
        """
        execution_id = str(uuid.uuid4())
        state = ExecutionState(
            execution_id=execution_id,
            task_id=task_id,
            plan_id=plan_id,
        )

        async with database.async_session_factory() as session:
            execution = ExecutionModel(
                id=execution_id,
                task_id=task_id,
                plan_id=plan_id,
                status="pending",
                state=state.to_dict(),
                total_tool_calls=0,
                total_cost=0.0,
            )
            session.add(execution)
            await session.commit()

        logger.info(f"Created execution {execution_id} for task {task_id}, plan {plan_id}")
        return state

    async def save_state(self, state: ExecutionState) -> None:
        """Persist the current execution state to the database.

        Args:
            state: The execution state to save.
        """
        async with database.async_session_factory() as session:
            result = await session.execute(
                select(ExecutionModel).where(ExecutionModel.id == state.execution_id)
            )
            execution = result.scalar_one_or_none()
            if execution is None:
                logger.error(f"Execution {state.execution_id} not found in DB")
                return

            execution.status = state.status
            execution.state = state.to_dict()
            execution.total_tool_calls = state.total_tool_calls
            execution.total_cost = state.total_cost
            execution.result = state.result
            execution.error = state.error

            if state.started_at and not execution.started_at:
                execution.started_at = state.started_at
            if state.completed_at:
                execution.completed_at = state.completed_at

            await session.commit()

    async def load_state(self, execution_id: str) -> ExecutionState | None:
        """Load execution state from the database.

        Used for recovering execution state after application restart.

        Args:
            execution_id: The execution ID to load.

        Returns:
            An ExecutionState object, or None if not found.
        """
        async with database.async_session_factory() as session:
            result = await session.execute(
                select(ExecutionModel).where(ExecutionModel.id == execution_id)
            )
            execution = result.scalar_one_or_none()
            if execution is None:
                return None

            state = ExecutionState(
                execution_id=execution.id,
                task_id=execution.task_id,
                plan_id=execution.plan_id,
            )
            state.status = execution.status
            state.total_tool_calls = execution.total_tool_calls or 0
            state.total_cost = execution.total_cost or 0.0
            state.result = execution.result
            state.error = execution.error
            state.started_at = execution.started_at
            state.completed_at = execution.completed_at

            # Restore state dict
            saved_state = execution.state or {}
            state.current_nodes = saved_state.get("current_nodes", [])
            state.completed_nodes = saved_state.get("completed_nodes", [])
            state.failed_nodes = saved_state.get("failed_nodes", [])
            state.outputs = saved_state.get("outputs", {})

            return state

    async def get_execution(self, execution_id: str) -> dict[str, Any] | None:
        """Get execution details as a dict (for API responses)."""
        async with database.async_session_factory() as session:
            result = await session.execute(
                select(ExecutionModel).where(ExecutionModel.id == execution_id)
            )
            execution = result.scalar_one_or_none()
            if execution is None:
                return None
            return execution.to_dict()


# --- Singleton ---

_state_manager: StateManager | None = None


def get_state_manager() -> StateManager:
    """Get the singleton StateManager instance."""
    global _state_manager
    if _state_manager is None:
        _state_manager = StateManager()
    return _state_manager