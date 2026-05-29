import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, Text, func
from app.db.types import GUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ParentChunk(Base):
    """Large text segment stored for LLM context. Never embedded directly.

    RLS policy (applied in migration):
        USING (tenant_id = current_setting('app.current_tenant')::uuid)
    """

    __tablename__ = "parent_chunks"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID, nullable=False, index=True)
    content_id: Mapped[uuid.UUID] = mapped_column(GUID, nullable=False, index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
