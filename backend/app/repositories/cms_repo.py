"""CMS content repository — tenant-scoped CRUD for ``cms_pages`` (feature 007).

Every function pins ``CmsPage.tenant_id`` to the caller's resolved tenant
(derived from the verified admin session at the route layer). RLS provides a
second enforcement layer at the DB level. There is no path here that returns
another tenant's pages.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.cms_page import CmsPage

_SLUG_MAX = 200


def slugify(text: str) -> str:
    """Derive a URL-ish slug from a title (lowercase, hyphen-separated)."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return (slug or "page")[:_SLUG_MAX]


async def list_pages(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    published: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[CmsPage]:
    """Return this tenant's pages, newest first. Always tenant-scoped."""
    query = select(CmsPage).where(CmsPage.tenant_id == tenant_id)
    if published is not None:
        query = query.where(CmsPage.is_published == published)
    query = query.order_by(CmsPage.created_at.desc()).limit(limit).offset(offset)
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_page(
    session: AsyncSession, *, tenant_id: uuid.UUID, page_id: uuid.UUID
) -> CmsPage | None:
    """Fetch one page for this tenant, or None (no cross-tenant disclosure)."""
    result = await session.execute(
        select(CmsPage).where(
            CmsPage.id == page_id, CmsPage.tenant_id == tenant_id
        )
    )
    return result.scalar_one_or_none()


async def slug_exists(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    slug: str,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    """True if ``slug`` is already used by this tenant (optionally excluding one id)."""
    query = select(CmsPage.id).where(
        CmsPage.tenant_id == tenant_id, CmsPage.slug == slug
    )
    if exclude_id is not None:
        query = query.where(CmsPage.id != exclude_id)
    result = await session.execute(query.limit(1))
    return result.first() is not None


async def create_page(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    title: str,
    slug: str,
    body: str,
    is_published: bool,
) -> CmsPage:
    page = CmsPage(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        title=title,
        slug=slug,
        body=body,
        is_published=is_published,
    )
    session.add(page)
    await session.flush()
    await session.refresh(page)  # populate server-default created_at/updated_at
    return page


async def delete_page(session: AsyncSession, *, page: CmsPage) -> None:
    await session.delete(page)
    await session.flush()


async def get_published_pages(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    content_ids: list[uuid.UUID] | None = None,
) -> list[dict]:
    """Return published pages as ``[{content_id, body}]`` for the ingestion pipeline.

    Only ``is_published`` pages are returned (unpublished content is never
    indexed/retrievable). ``tenant_id`` is the injected parameter — never read
    from a row.
    """
    query = select(CmsPage).where(
        CmsPage.tenant_id == tenant_id, CmsPage.is_published.is_(True)
    )
    if content_ids:
        query = query.where(CmsPage.id.in_(content_ids))
    result = await session.execute(query)
    return [
        {"content_id": page.id, "body": page.body}
        for page in result.scalars().all()
    ]
