"""CMS content service (feature 007, US1).

Orchestrates tenant-scoped CRUD over ``cms_repo`` and schedules background
re-indexing of authored content into the existing RAG pipeline.

Tenant safety:
- All reads/writes are pinned to the caller's resolved tenant (passed in from
  the route's ``AdminIdentityDep``); tenant id is never taken from client input.
- The background re-index opens its OWN tenant-scoped session (the request
  session is closed by the time the response returns), setting the
  ``app.current_tenant`` RLS GUC so every write resolves under FORCE RLS.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import BackgroundTasks
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.cms_page import CmsPage
from app.db.session import AsyncSessionLocal
from app.repos.chunk_repo import ChunkRepo
from app.repositories import cms_repo
from app.services.ingestion import ingest_tenant_content
from app.tenancy.rls import TENANT_CONTEXT_GUC

logger = logging.getLogger(__name__)


class CmsPageNotFound(Exception):
    """Requested page does not exist for this tenant."""


class CmsSlugConflict(Exception):
    """Slug already used by another page in this tenant."""


# --- CRUD orchestration -----------------------------------------------------


async def list_pages(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    published: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[CmsPage]:
    return await cms_repo.list_pages(
        db, tenant_id=tenant_id, published=published, limit=limit, offset=offset
    )


async def get_page(
    db: AsyncSession, *, tenant_id: uuid.UUID, page_id: uuid.UUID
) -> CmsPage:
    page = await cms_repo.get_page(db, tenant_id=tenant_id, page_id=page_id)
    if page is None:
        raise CmsPageNotFound(str(page_id))
    return page


async def create_page(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    title: str,
    body: str,
    slug: str | None,
    is_published: bool,
) -> CmsPage:
    resolved_slug = (slug or cms_repo.slugify(title)).strip()
    if await cms_repo.slug_exists(db, tenant_id=tenant_id, slug=resolved_slug):
        raise CmsSlugConflict(resolved_slug)
    return await cms_repo.create_page(
        db,
        tenant_id=tenant_id,
        title=title,
        slug=resolved_slug,
        body=body,
        is_published=is_published,
    )


async def update_page(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    page_id: uuid.UUID,
    title: str | None = None,
    body: str | None = None,
    slug: str | None = None,
    is_published: bool | None = None,
) -> CmsPage:
    page = await get_page(db, tenant_id=tenant_id, page_id=page_id)
    if slug is not None:
        new_slug = slug.strip()
        if await cms_repo.slug_exists(
            db, tenant_id=tenant_id, slug=new_slug, exclude_id=page.id
        ):
            raise CmsSlugConflict(new_slug)
        page.slug = new_slug
    if title is not None:
        page.title = title
    if body is not None:
        page.body = body
    if is_published is not None:
        page.is_published = is_published
    await db.flush()
    await db.refresh(page)  # pick up onupdate updated_at
    return page


async def delete_page(
    db: AsyncSession, *, tenant_id: uuid.UUID, page_id: uuid.UUID
) -> None:
    page = await get_page(db, tenant_id=tenant_id, page_id=page_id)
    await cms_repo.delete_page(db, page=page)


# --- background re-index ----------------------------------------------------


def schedule_reindex(
    background_tasks: BackgroundTasks, app, tenant_id: uuid.UUID, page_id: uuid.UUID
) -> None:
    """Schedule a background re-index of one page after a create/update."""
    background_tasks.add_task(_reindex_page, app, str(tenant_id), str(page_id))


def schedule_removal(
    background_tasks: BackgroundTasks, app, tenant_id: uuid.UUID, page_id: uuid.UUID
) -> None:
    """Schedule background removal of a deleted page's chunks."""
    background_tasks.add_task(_remove_page_chunks, app, str(tenant_id), str(page_id))


async def _tenant_session(tenant_id: str) -> AsyncSession:
    """Open a session with the RLS tenant GUC set (caller must close/commit)."""
    session = AsyncSessionLocal()
    await session.execute(
        text("SELECT set_config(:var, :tid, true)"),
        {"var": TENANT_CONTEXT_GUC, "tid": tenant_id},
    )
    return session


async def _reindex_page(app, tenant_id: str, page_id: str) -> None:
    """Delete stale chunks for the page, then re-ingest if it is published.

    Runs outside the request; opens its own tenant-scoped session. Failures are
    logged (ids/status only) and do not lose the already-saved content.
    """
    embedder = getattr(app.state, "embedder", None)
    if embedder is None:
        logger.warning("cms.reindex_no_embedder tenant=%s page=%s", tenant_id, page_id)
        return
    try:
        session = await _tenant_session(tenant_id)
        async with session:
            # Clear any prior version's chunks first (covers unpublish), then
            # ingest re-adds child/parent chunks only for published pages.
            await ChunkRepo(session).delete_chunks_for_content(
                uuid.UUID(page_id), uuid.UUID(tenant_id)
            )
            await ingest_tenant_content(
                tenant_id=tenant_id,
                content_ids=[page_id],
                db=session,
                embedder=embedder,
            )
            await session.commit()
        logger.info("cms.reindex_done tenant=%s page=%s", tenant_id, page_id)
    except Exception:
        logger.exception("cms.reindex_failed tenant=%s page=%s", tenant_id, page_id)


async def _remove_page_chunks(app, tenant_id: str, page_id: str) -> None:
    """Delete a page's chunks after the page itself was deleted."""
    try:
        session = await _tenant_session(tenant_id)
        async with session:
            await ChunkRepo(session).delete_chunks_for_content(
                uuid.UUID(page_id), uuid.UUID(tenant_id)
            )
            await session.commit()
        logger.info("cms.remove_chunks_done tenant=%s page=%s", tenant_id, page_id)
    except Exception:
        logger.exception("cms.remove_chunks_failed tenant=%s page=%s", tenant_id, page_id)
