import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB

from app.db.types import GUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WidgetConfig(Base):
    """Per-tenant widget appearance and behaviour configuration.

    allowed_origins is a JSON list of origin strings validated server-side on
    every widget token exchange request — never trusted from the client.
    """

    __tablename__ = "widget_configs"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    public_widget_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    allowed_origins: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    persona_name: Mapped[str | None] = mapped_column(String, nullable=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
