"""SQLAlchemy models for executions and execution events."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, Integer, Float, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionModel(Base):
    """A single execution instance of a workflow."""

    __tablename__ = "executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=False, index=True)
    plan_id: Mapped[str] = mapped_column(String(36), ForeignKey("plans.id"), nullable=False)

    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    # Statuses: pending, running, paused, completed, failed, cancelled

    # Execution state (current_nodes, completed_nodes, failed_nodes, outputs)
    state: Mapped[dict] = mapped_column(JSON, default=dict)

    # ADK session ID for state persistence
    adk_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Metrics
    total_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_tool_calls: Mapped[int] = mapped_column(Integer, default=0)

    # Final result
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "plan_id": self.plan_id,
            "status": self.status,
            "state": self.state,
            "adk_session_id": self.adk_session_id,
            "total_duration_seconds": self.total_duration_seconds,
            "total_cost": self.total_cost,
            "total_tool_calls": self.total_tool_calls,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class ExecutionEventModel(Base):
    """An event emitted during execution."""

    __tablename__ = "execution_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    execution_id: Mapped[str] = mapped_column(String(36), ForeignKey("executions.id"), nullable=False, index=True)

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # Types: TASK_CREATED, PLAN_CREATED, PLAN_APPROVED, PLAN_REJECTED,
    #        AGENT_CREATED, AGENT_STARTED, AGENT_COMPLETED, AGENT_FAILED,
    #        TOOL_STARTED, TOOL_COMPLETED, TOOL_FAILED,
    #        HUMAN_APPROVAL_REQUIRED, HUMAN_APPROVED, HUMAN_REJECTED,
    #        TASK_COMPLETED, TASK_FAILED,
    #        EVALUATION_STARTED, EVALUATION_COMPLETED,
    #        SKILL_CREATED, SKILL_VERSION_CREATED

    agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tool_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Additional event data
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "execution_id": self.execution_id,
            "event_type": self.event_type,
            "agent_id": self.agent_id,
            "tool_id": self.tool_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "data": self.data,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }