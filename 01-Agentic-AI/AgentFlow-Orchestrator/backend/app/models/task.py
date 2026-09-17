"""SQLAlchemy model for tasks."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, String as SAString
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TaskModel(Base):
    """A task created from a user intent."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(SAString(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    intent: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="created", nullable=False)
    # Statuses: created, planning, planned, approved, rejected, executing, completed, failed

    user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "intent": self.intent,
            "status": self.status,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }