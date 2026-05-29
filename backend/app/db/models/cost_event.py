import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, func
from app.db.types import GUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CostEvent(Base):
    """Per-call token and cost record for a single tenant."""

    __tablename__ = "cost_events"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    call_type: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(precision=10, scale=6), nullable=False, default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
