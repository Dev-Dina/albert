import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from app.db.types import GUID
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.db.base import Base


class ChildChunk(Base):
    """Small text segment used only for similarity search.

    Embedding dimension is 768 (Gemini text-embedding-004).
    Linked to its parent for context retrieval after reranking.

    RLS policy (applied in migration):
        USING (tenant_id = current_setting('app.current_tenant')::uuid)
    """

    __tablename__ = "child_chunks"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(GUID, nullable=False, index=True)
    parent_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("parent_chunks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list] = mapped_column(Vector(768), nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
