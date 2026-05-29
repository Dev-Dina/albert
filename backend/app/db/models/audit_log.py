import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB

from app.db.types import GUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    """Platform-wide security/audit trail."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        GUID, primary_key=True, default=uuid.uuid4
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    target_tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String, nullable=False)
    # Attribute is "meta" because SQLAlchemy reserves ``metadata``; DB column is "metadata".
    meta: Mapped[dict[str, Any]] = mapped_column(
        # JSONB on Postgres; JSON on SQLite so unit tests can create_all without a
        # live Postgres. Postgres DDL and Alembic migrations are unchanged.
        "metadata",
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        default=dict,
        server_default="{}",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
