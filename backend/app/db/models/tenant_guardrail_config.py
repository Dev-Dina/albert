import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB

from app.db.types import GUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TenantGuardrailConfig(Base):
    """Tenant-configurable guardrail settings.

    These are the TENANT rails — allowed/blocked topics, tone, enabled tools.
    Platform rails (injection detection, jailbreak, cross-tenant refusal, PII)
    are hardcoded and CANNOT be configured or disabled by any tenant.
    """

    __tablename__ = "tenant_guardrail_configs"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    allowed_topics: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    blocked_topics: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    refusal_tone: Mapped[str | None] = mapped_column(String, nullable=True)
    # Subset of ["rag_search", "capture_lead", "escalate"] — tenant may disable some.
    enabled_tools: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=lambda: ["rag_search", "capture_lead", "escalate"]
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
