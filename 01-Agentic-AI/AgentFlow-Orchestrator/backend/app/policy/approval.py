"""Approval Manager — creates, resolves, and tracks human approval requests.

Matches instruction.md section 22 (Human-in-the-Loop).

Approval lifecycle:
  Agent requires approval
  → Orchestrator pauses execution (status = "paused")
  → ApprovalManager creates an ApprovalModel (status = "pending")
  → Emits HUMAN_APPROVAL_REQUIRED event
  → User approves → status = "approved" → HUMAN_APPROVED event → execution resumes
  → User rejects → status = "rejected" → HUMAN_REJECTED event → execution fails

The approval manager also supports an in-memory event system so the
orchestrator can wait for approval asynchronously.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update

from app.db import database
from app.models.approval import ApprovalModel
from app.orchestrator.events import get_event_manager

logger = logging.getLogger(__name__)


class ApprovalNotFoundError(Exception):
    """Raised when an approval request is not found."""


class ApprovalAlreadyResolvedError(Exception):
    """Raised when trying to resolve an already-resolved approval."""


class ApprovalManager:
    """Manages human approval requests.

    Creates approval requests, waits for resolution, and tracks
    the approval state in the database.

    The manager uses asyncio.Event to allow the orchestrator to
    wait for approval without busy-polling.
    """

    def __init__(self) -> None:
        # In-memory events for waiting on approval: approval_id → asyncio.Event
        self._pending_events: dict[str, asyncio.Event] = {}
        # Track approval decisions: approval_id → "approved" | "rejected"
        self._decisions: dict[str, str] = {}

    async def create_request(
        self,
        execution_id: str,
        approval_type: str,
        context: dict[str, Any],
        task_id: str | None = None,
    ) -> str:
        """Create a new approval request.

        Args:
            execution_id: The execution this approval belongs to.
            approval_type: Type of approval ("tool", "agent", "destructive_action").
            context: Context data about what's being approved.
            task_id: Optional task ID.

        Returns:
            The approval request ID.
        """
        approval_id = str(uuid.uuid4())

        # Persist to database
        async with database.async_session_factory() as session:
            approval = ApprovalModel(
                id=approval_id,
                task_id=task_id,
                execution_id=execution_id,
                approval_type=approval_type,
                status="pending",
                context=context,
            )
            session.add(approval)
            await session.commit()

        # Set up in-memory event for waiting
        event = asyncio.Event()
        self._pending_events[approval_id] = event

        # Emit event
        event_manager = get_event_manager()
        await event_manager.emit(
            execution_id=execution_id,
            event_type="HUMAN_APPROVAL_REQUIRED",
            data={
                "approval_id": approval_id,
                "approval_type": approval_type,
                "context": context,
            },
        )

        logger.info(
            f"Created approval request {approval_id} "
            f"(type={approval_type}, execution={execution_id})"
        )
        return approval_id

    async def approve(self, approval_id: str, user_id: str | None = None) -> dict[str, Any]:
        """Approve a pending approval request.

        Args:
            approval_id: The approval to approve.
            user_id: Who approved it.

        Returns:
            The updated approval dict.

        Raises:
            ApprovalNotFoundError: If the approval doesn't exist.
            ApprovalAlreadyResolvedError: If already approved/rejected.
        """
        async with database.async_session_factory() as session:
            result = await session.execute(
                select(ApprovalModel).where(ApprovalModel.id == approval_id)
            )
            approval = result.scalar_one_or_none()
            if approval is None:
                raise ApprovalNotFoundError(f"Approval '{approval_id}' not found")

            if approval.status != "pending":
                raise ApprovalAlreadyResolvedError(
                    f"Approval '{approval_id}' is already '{approval.status}'"
                )

            approval.status = "approved"
            approval.user_id = user_id
            approval.resolved_at = datetime.now(timezone.utc)
            await session.commit()

            approval_dict = approval.to_dict()

        # Signal the waiting orchestrator
        self._decisions[approval_id] = "approved"
        event = self._pending_events.get(approval_id)
        if event:
            event.set()

        # Emit event
        event_manager = get_event_manager()
        await event_manager.emit(
            execution_id=approval_dict.get("execution_id", ""),
            event_type="HUMAN_APPROVED",
            data={"approval_id": approval_id, "user_id": user_id},
        )

        logger.info(f"Approval {approval_id} approved by {user_id or 'unknown'}")
        return approval_dict

    async def reject(self, approval_id: str, user_id: str | None = None) -> dict[str, Any]:
        """Reject a pending approval request.

        Args:
            approval_id: The approval to reject.
            user_id: Who rejected it.

        Returns:
            The updated approval dict.

        Raises:
            ApprovalNotFoundError: If the approval doesn't exist.
            ApprovalAlreadyResolvedError: If already approved/rejected.
        """
        async with database.async_session_factory() as session:
            result = await session.execute(
                select(ApprovalModel).where(ApprovalModel.id == approval_id)
            )
            approval = result.scalar_one_or_none()
            if approval is None:
                raise ApprovalNotFoundError(f"Approval '{approval_id}' not found")

            if approval.status != "pending":
                raise ApprovalAlreadyResolvedError(
                    f"Approval '{approval_id}' is already '{approval.status}'"
                )

            approval.status = "rejected"
            approval.user_id = user_id
            approval.resolved_at = datetime.now(timezone.utc)
            await session.commit()

            approval_dict = approval.to_dict()

        # Signal the waiting orchestrator
        self._decisions[approval_id] = "rejected"
        event = self._pending_events.get(approval_id)
        if event:
            event.set()

        # Emit event
        event_manager = get_event_manager()
        await event_manager.emit(
            execution_id=approval_dict.get("execution_id", ""),
            event_type="HUMAN_REJECTED",
            data={"approval_id": approval_id, "user_id": user_id},
        )

        logger.info(f"Approval {approval_id} rejected by {user_id or 'unknown'}")
        return approval_dict

    async def wait_for_approval(
        self,
        approval_id: str,
        timeout: float = 300.0,
    ) -> str:
        """Wait for an approval to be resolved.

        Blocks until the approval is approved or rejected, or timeout.

        Args:
            approval_id: The approval to wait for.
            timeout: Maximum time to wait in seconds.

        Returns:
            "approved" or "rejected".

        Raises:
            asyncio.TimeoutError: If the approval is not resolved within timeout.
        """
        event = self._pending_events.get(approval_id)
        if event is None:
            # No event — check if already resolved
            decision = self._decisions.get(approval_id)
            if decision:
                return decision
            # Not found — might have been resolved before this call
            async with database.async_session_factory() as session:
                result = await session.execute(
                    select(ApprovalModel).where(ApprovalModel.id == approval_id)
                )
                approval = result.scalar_one_or_none()
                if approval and approval.status != "pending":
                    return approval.status
            raise ApprovalNotFoundError(f"Approval '{approval_id}' not found or no event")

        await asyncio.wait_for(event.wait(), timeout=timeout)
        return self._decisions.get(approval_id, "approved")

    async def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        """Get an approval request by ID."""
        async with database.async_session_factory() as session:
            result = await session.execute(
                select(ApprovalModel).where(ApprovalModel.id == approval_id)
            )
            approval = result.scalar_one_or_none()
            if approval is None:
                return None
            return approval.to_dict()

    async def list_pending(self, execution_id: str | None = None) -> list[dict[str, Any]]:
        """List pending approval requests.

        Args:
            execution_id: Optional filter by execution ID.

        Returns:
            List of pending approval dicts.
        """
        async with database.async_session_factory() as session:
            query = select(ApprovalModel).where(ApprovalModel.status == "pending")
            if execution_id:
                query = query.where(ApprovalModel.execution_id == execution_id)
            query = query.order_by(ApprovalModel.created_at)

            result = await session.execute(query)
            approvals = result.scalars().all()
            return [a.to_dict() for a in approvals]

    def cleanup(self, approval_id: str) -> None:
        """Clean up in-memory tracking for a resolved approval."""
        self._pending_events.pop(approval_id, None)
        self._decisions.pop(approval_id, None)


# --- Singleton ---

_approval_manager: ApprovalManager | None = None


def get_approval_manager() -> ApprovalManager:
    """Get the singleton ApprovalManager instance."""
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = ApprovalManager()
    return _approval_manager