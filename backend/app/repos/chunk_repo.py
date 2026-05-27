import uuid
import logging
from dataclasses import dataclass

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.child_chunk import ChildChunk
from app.db.models.parent_chunk import ParentChunk

logger = logging.getLogger(__name__)


@dataclass
class ParentChunkRow:
    id: uuid.UUID
    tenant_id: uuid.UUID
    content_id: uuid.UUID
    text: str
    chunk_index: int


@dataclass
class ChildChunkRow:
    id: uuid.UUID
    tenant_id: uuid.UUID
    parent_id: uuid.UUID
    text: str
    embedding: list[float]
    chunk_index: int


class ChunkRepo:
    """Tenant-scoped database access for parent and child chunks.

    Every method takes an explicit tenant_id and filters by it at the
    query layer. RLS provides a second enforcement layer at the DB level.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def delete_chunks_for_content(self, content_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        """Delete all parent (and cascaded child) chunks for a given content_id + tenant_id."""
        stmt = delete(ParentChunk).where(
            ParentChunk.content_id == content_id,
            ParentChunk.tenant_id == tenant_id,
        )
        await self._db.execute(stmt)

    async def write_parent_chunks(self, rows: list[ParentChunkRow]) -> None:
        """Bulk-insert parent chunk rows."""
        for row in rows:
            obj = ParentChunk(
                id=row.id,
                tenant_id=row.tenant_id,
                content_id=row.content_id,
                text=row.text,
                chunk_index=row.chunk_index,
            )
            self._db.add(obj)

    async def write_child_chunks(self, rows: list[ChildChunkRow]) -> None:
        """Bulk-insert child chunk rows with embeddings."""
        for row in rows:
            obj = ChildChunk(
                id=row.id,
                tenant_id=row.tenant_id,
                parent_id=row.parent_id,
                text=row.text,
                embedding=row.embedding,
                chunk_index=row.chunk_index,
            )
            self._db.add(obj)

    async def search_children(
        self,
        embedding: list[float],
        tenant_id: uuid.UUID,
        top_k: int,
    ) -> list[ChildChunk]:
        """ANN search over child_chunks filtered by tenant_id. Returns top_k results."""
        # Cast embedding list to a postgres vector literal for the cosine distance operator.
        vec_literal = "[" + ",".join(str(v) for v in embedding) + "]"
        stmt = (
            select(ChildChunk)
            .where(ChildChunk.tenant_id == tenant_id)
            .order_by(
                text(f"embedding <=> '{vec_literal}'::vector")
            )
            .limit(top_k)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def fetch_parents_by_ids(
        self,
        parent_ids: list[uuid.UUID],
        tenant_id: uuid.UUID,
    ) -> list[ParentChunk]:
        """Fetch parent chunk rows by IDs, scoped to tenant_id."""
        if not parent_ids:
            return []
        stmt = select(ParentChunk).where(
            ParentChunk.id.in_(parent_ids),
            ParentChunk.tenant_id == tenant_id,
        )
        result = await self._db.execute(stmt)
        rows = {r.id: r for r in result.scalars().all()}
        # Preserve the order of parent_ids (reranker order).
        return [rows[pid] for pid in parent_ids if pid in rows]
