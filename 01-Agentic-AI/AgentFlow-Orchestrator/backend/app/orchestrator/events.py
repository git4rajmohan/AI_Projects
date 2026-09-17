"""Event system — emits and persists execution events.

Matches instruction.md section 17 (Event System).

Events are stored in the database (ExecutionEventModel) and can also
be streamed to clients via SSE (Server-Sent Events).

Event types:
- TASK_CREATED, TASK_COMPLETED, TASK_FAILED
- PLAN_CREATED, PLAN_APPROVED, PLAN_REJECTED
- AGENT_CREATED, AGENT_STARTED, AGENT_COMPLETED, AGENT_FAILED
- TOOL_STARTED, TOOL_COMPLETED, TOOL_FAILED
- HUMAN_APPROVAL_REQUIRED, HUMAN_APPROVED, HUMAN_REJECTED
- EVALUATION_STARTED, EVALUATION_COMPLETED
- SKILL_CREATED, SKILL_VERSION_CREATED
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import database
from app.models.execution import ExecutionEventModel

logger = logging.getLogger(__name__)


class EventManager:
    """Manages execution events — persists to DB and supports streaming.

    Also supports an in-memory event queue for SSE streaming so clients
    can receive events in real-time without polling the database.
    """

    def __init__(self) -> None:
        # In-memory event queues for SSE streaming: execution_id → asyncio.Queue
        self._queues: dict[str, list[asyncio.Queue]] = {}

    async def emit(
        self,
        execution_id: str,
        event_type: str,
        agent_id: str | None = None,
        tool_id: str | None = None,
        status: str | None = None,
        duration_ms: int | None = None,
        error: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Emit an execution event.

        Persists the event to the database and pushes it to any
        active SSE subscriber queues.

        Args:
            execution_id: The execution this event belongs to.
            event_type: One of the EVENT_TYPES listed above.
            agent_id: The agent this event relates to (if any).
            tool_id: The tool this event relates to (if any).
            status: Sub-status (e.g., "success", "failure").
            duration_ms: Duration in milliseconds (if relevant).
            error: Error message (if relevant).
            data: Additional event-specific data.
        """
        event = ExecutionEventModel(
            id=str(uuid.uuid4()),
            execution_id=execution_id,
            event_type=event_type,
            agent_id=agent_id,
            tool_id=tool_id,
            status=status,
            duration_ms=duration_ms,
            error=error,
            data=data,
            timestamp=datetime.now(timezone.utc),
        )

        # Persist to database
        try:
            async with database.async_session_factory() as session:
                session.add(event)
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to persist event {event_type}: {e}")

        # Push to SSE subscriber queues
        event_dict = event.to_dict()
        for queue in self._queues.get(execution_id, []):
            try:
                queue.put_nowait(event_dict)
            except asyncio.QueueFull:
                logger.warning(f"SSE queue full for execution {execution_id}, dropping event")

        logger.debug(f"Event emitted: {event_type} for execution {execution_id}")

    def subscribe(self, execution_id: str) -> asyncio.Queue:
        """Subscribe to real-time events for an execution.

        Returns an asyncio.Queue that will receive event dicts as they are emitted.
        Call unsubscribe() when done to avoid memory leaks.
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        if execution_id not in self._queues:
            self._queues[execution_id] = []
        self._queues[execution_id].append(queue)
        return queue

    def unsubscribe(self, execution_id: str, queue: asyncio.Queue) -> None:
        """Unsubscribe from real-time events."""
        if execution_id in self._queues:
            try:
                self._queues[execution_id].remove(queue)
            except ValueError:
                pass
            if not self._queues[execution_id]:
                del self._queues[execution_id]

    async def get_events(self, execution_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Get all events for an execution from the database.

        Args:
            execution_id: The execution ID.
            limit: Maximum number of events to return.

        Returns:
            List of event dicts, ordered by timestamp.
        """
        async with database.async_session_factory() as session:
            result = await session.execute(
                select(ExecutionEventModel)
                .where(ExecutionEventModel.execution_id == execution_id)
                .order_by(ExecutionEventModel.timestamp)
                .limit(limit)
            )
            events = result.scalars().all()
            return [e.to_dict() for e in events]

    async def stream_events(
        self,
        execution_id: str,
        max_seconds: float = 300.0,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream events for an execution as an async generator.

        Yields events as they are emitted. Also yields any historical
        events first (from the database), then live events.

        Args:
            execution_id: The execution ID.
            max_seconds: Maximum time to wait for events (timeout).

        Yields:
            Event dicts.
        """
        # First, yield historical events
        historical = await self.get_events(execution_id)
        for event in historical:
            yield event

        # Then, subscribe to live events
        queue = self.subscribe(execution_id)
        try:
            deadline = asyncio.get_event_loop().time() + max_seconds
            while True:
                timeout = max(0.1, deadline - asyncio.get_event_loop().time())
                if timeout <= 0:
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=timeout)
                    yield event
                except asyncio.TimeoutError:
                    break
        finally:
            self.unsubscribe(execution_id, queue)


# --- Singleton ---

_event_manager: EventManager | None = None


def get_event_manager() -> EventManager:
    """Get the singleton EventManager instance."""
    global _event_manager
    if _event_manager is None:
        _event_manager = EventManager()
    return _event_manager