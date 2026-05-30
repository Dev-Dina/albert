import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, func
from app.db.types import GUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Escalation(Base):
    """Captured human-handoff context for a conversation (1:1 per conversation).

    Written by the ``escalate`` tool (upsert) under the verified tenant/session
    context — tenant_id is never taken from client input. Protected by FORCE ROW
    LEVEL SECURITY on ``app.current_tenant`` (migration 0015).
    """

    __tablename__ = "escalations"
    __table_args__ = (
        UniqueConstraint("conversation_id", name="uq_escalations_conversation"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Two-state lifecycle (feature 008): "open" (default) | "resolved". Valid
    # values are enforced in the app layer (Pydantic enum + escalation_lifecycle);
    # there is no DB CHECK constraint (see migration 0016 / research.md D3).
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="open", server_default="open"
    )
    # Light audit trail, populated on resolve and cleared on reopen. ``resolved_by``
    # is the acting admin's user_id (same tenant), stored without a FK (research D1).
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
