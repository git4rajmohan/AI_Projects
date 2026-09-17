"""SQLAlchemy model for tools."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, DateTime, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ToolModel(Base):
    """A registered tool available to agents."""

    __tablename__ = "tools"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Permission level: READ, WRITE, EXTERNAL_ACTION, DESTRUCTIVE
    permission_level: Mapped[str] = mapped_column(String(50), default="READ", nullable=False)

    # Input/output schemas as JSON
    input_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Configuration (e.g., API keys, endpoints) — never log this
    config: Mapped[dict] = mapped_column(JSON, default=dict)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "permission_level": self.permission_level,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "config": self.config,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }