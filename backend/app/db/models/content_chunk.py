import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, String, Text, func
from app.db.types import GUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ContentChunk(Base):
    """A text chunk with its embedding vector for RAG retrieval.

    Must always be retrieved with a tenant_id filter — both RLS and explicit
    repo predicate.  The most common vector leak is a search that forgets
    the tenant filter.
    """

    __tablename__ = "content_chunks"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cms_page_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID, ForeignKey("cms_pages.id", ondelete="CASCADE"), nullable=True
    )
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any | None] = mapped_column(Vector(1536), nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
