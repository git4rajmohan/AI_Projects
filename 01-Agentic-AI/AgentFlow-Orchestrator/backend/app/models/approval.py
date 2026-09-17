"""SQLAlchemy model for approval requests."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalModel(Base):
    """A human approval request for a plan or tool execution."""

    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("tasks.id"), nullable=True)
    execution_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("executions.id"), nullable=True)

    approval_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Types: plan, tool, destructive_action

    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    # Statuses: pending, approved, rejected, expired

    # Context data (what is being approved)
    context: Mapped[dict] = mapped_column(JSON, default=dict)

    # Who approved/rejected
    user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "execution_id": self.execution_id,
            "approval_type": self.approval_type,
            "status": self.status,
            "context": self.context,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }