import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Widget(Base):
    """A per-tenant embeddable chat instance (data-model.md E1)."""

    __tablename__ = "widgets"
    __table_args__ = (
        CheckConstraint("status IN ('enabled', 'disabled')", name="ck_widgets_status"),
        CheckConstraint(
            "public_widget_id ~ '^[A-Za-z0-9]{22}$'",
            name="ck_widgets_public_widget_id_format",
        ),
        CheckConstraint("char_length(greeting) <= 500", name="ck_widgets_greeting_length"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    public_widget_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    theme: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    greeting: Mapped[str] = mapped_column(
        String(length=500), nullable=False, default="", server_default=""
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="enabled", server_default="enabled"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
