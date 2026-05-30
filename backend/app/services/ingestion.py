import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.embedder import EmbedderAdapter, EmbedError
from app.core.config import settings
from app.cost import record_cost_event
from app.repos.chunk_repo import ChunkRepo, ChildChunkRow, ParentChunkRow

logger = logging.getLogger(__name__)

_PARENT_MAX_CHARS = 2048
_CHILD_MAX_CHARS = 512
_PARENT_TARGET = 1024
_CHILD_TARGET = 256
_EMBED_BATCH_SIZE = 100


@dataclass
class IngestionResult:
    tenant_id: str
    pages_processed: int
    parent_chunks_written: int
    child_chunks_written: int
    errors: list[str] = field(default_factory=list)
    success: bool = True


def _split_into_chunks(text: str, target: int, max_chars: int) -> list[str]:
    """Split text into chunks of approximately target chars, hard-capped at max_chars.

    Splits on whitespace boundaries to avoid cutting mid-word.
    """
    if not text or not text.strip():
        return []
    words = text.split()
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for word in words:
        word_len = len(word) + 1  # +1 for space
        if current_len + word_len > max_chars and current:
            chunks.append(" ".join(current))
            current = [word]
            current_len = word_len
        else:
            current.append(word)
            current_len += word_len
            if current_len >= target and len(" ".join(current)) >= target:
                chunks.append(" ".join(current))
                current = []
                current_len = 0
    if current:
        chunks.append(" ".join(current))
    return chunks


async def ingest_tenant_content(
    *,
    tenant_id: str,
    content_ids: list[str] | None = None,
    db: AsyncSession,
    embedder: EmbedderAdapter,
) -> IngestionResult:
    """Chunk, embed, and index CMS content for a tenant.

    - Pulls content via content_repo stub (Owner A dependency).
    - Splits each page into parent chunks (~1024 chars) then child chunks (~256 chars).
    - Embeds children in batches of 100.
    - Tags every embed call with tenant_id for cost attribution.
    - Writes parent then child rows in a single transaction per page.
    - Idempotent: deletes existing chunks for content_id before writing.
    - On embed error: skips the page, records error, continues.
    - tenant_id is NEVER read from content rows — always the injected parameter.
    """
    tenant_uuid = uuid.UUID(tenant_id)
    repo = ChunkRepo(db)
    result = IngestionResult(tenant_id=tenant_id, pages_processed=0, parent_chunks_written=0, child_chunks_written=0)

    # Fetch published CMS pages for this tenant (feature 007 — replaces the stub).
    pages = await _fetch_content_pages(db, tenant_uuid, content_ids)

    for page in pages:
        content_id = page["content_id"]
        body = page.get("body", "") or ""

        if not body.strip():
            logger.debug("ingestion.skip_empty content_id=%s", content_id)
            continue

        try:
            parent_texts = _split_into_chunks(body, _PARENT_TARGET, _PARENT_MAX_CHARS)
            parent_rows: list[ParentChunkRow] = []
            for idx, ptext in enumerate(parent_texts):
                parent_rows.append(ParentChunkRow(
                    id=uuid.uuid4(),
                    tenant_id=tenant_uuid,
                    content_id=content_id,
                    text=ptext,
                    chunk_index=idx,
                ))

            child_rows: list[ChildChunkRow] = []
            for parent_row in parent_rows:
                child_texts = _split_into_chunks(parent_row.text, _CHILD_TARGET, _CHILD_MAX_CHARS)
                for cidx, ctext in enumerate(child_texts):
                    child_rows.append(ChildChunkRow(
                        id=uuid.uuid4(),
                        tenant_id=tenant_uuid,
                        parent_id=parent_row.id,
                        text=ctext,
                        embedding=[],  # filled below after batching
                        chunk_index=cidx,
                    ))

            # Embed children in batches.
            all_embeddings: list[list[float]] = []
            for batch_start in range(0, len(child_rows), _EMBED_BATCH_SIZE):
                batch = child_rows[batch_start: batch_start + _EMBED_BATCH_SIZE]
                batch_texts = [r.text for r in batch]
                logger.debug(
                    "ingestion.embed_batch tenant=%s content_id=%s batch_size=%d",
                    tenant_id, content_id, len(batch_texts),
                )
                embeddings = await embedder.embed_batch(batch_texts)
                all_embeddings.extend(embeddings)
                try:
                    await record_cost_event(
                        db=db,
                        tenant_id=tenant_uuid,
                        call_type="embedding",
                        model=settings.gemini_embedding_model,
                        input_tokens=len(batch_texts),
                    )
                except Exception:
                    logger.warning("ingestion.cost_record_failed tenant=%s", tenant_id)

            for i, emb in enumerate(all_embeddings):
                child_rows[i] = ChildChunkRow(
                    id=child_rows[i].id,
                    tenant_id=child_rows[i].tenant_id,
                    parent_id=child_rows[i].parent_id,
                    text=child_rows[i].text,
                    embedding=emb,
                    chunk_index=child_rows[i].chunk_index,
                )

            # Write atomically: delete existing → write parents → write children.
            # Flush parents BEFORE children: there is no ORM relationship() between
            # ParentChunk and ChildChunk, so the unit-of-work does not guarantee
            # parent INSERTs precede child INSERTs in a single flush — without this
            # the child_chunks_parent_id_fkey FK is violated.
            await repo.delete_chunks_for_content(content_id, tenant_uuid)
            await repo.write_parent_chunks(parent_rows)
            await db.flush()
            await repo.write_child_chunks(child_rows)
            await db.flush()

            result.pages_processed += 1
            result.parent_chunks_written += len(parent_rows)
            result.child_chunks_written += len(child_rows)
            logger.info(
                "ingestion.page_done tenant=%s content_id=%s parents=%d children=%d",
                tenant_id, content_id, len(parent_rows), len(child_rows),
            )

        except EmbedError as exc:
            msg = f"content_id={content_id}: embed error — {exc}"
            logger.error("ingestion.embed_error %s", msg)
            result.errors.append(msg)
            await db.rollback()

        except Exception as exc:
            msg = f"content_id={content_id}: write error — {exc}"
            logger.error("ingestion.write_error %s", msg)
            result.errors.append(msg)
            await db.rollback()

    if result.errors and result.pages_processed == 0:
        result.success = False

    return result


async def _fetch_content_pages(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    content_ids: list[str] | None,
) -> list[dict]:
    """Fetch this tenant's PUBLISHED CMS pages as ``[{content_id, body}]``.

    Reads via ``cms_repo.get_published_pages``; unpublished pages are excluded so
    they are never indexed/retrievable. ``tenant_id`` is the injected parameter —
    never read from a content row.
    """
    from app.repositories import cms_repo  # local import avoids import cycles

    uuid_ids: list[uuid.UUID] | None = None
    if content_ids:
        uuid_ids = [cid if isinstance(cid, uuid.UUID) else uuid.UUID(str(cid)) for cid in content_ids]
    pages = await cms_repo.get_published_pages(
        db, tenant_id=tenant_id, content_ids=uuid_ids
    )
    logger.debug(
        "ingestion._fetch_content_pages tenant=%s pages=%d", tenant_id, len(pages)
    )
    return pages
