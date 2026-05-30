"""Tenant-scoped allowed-origin repository."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.widget_allowed_origin import WidgetAllowedOrigin


async def list_by_tenant(
    session: AsyncSession, tenant_id: uuid.UUID
) -> list[WidgetAllowedOrigin]:
    result = await session.execute(
        select(WidgetAllowedOrigin)
        .where(WidgetAllowedOrigin.tenant_id == tenant_id)
        .order_by(WidgetAllowedOrigin.created_at)
    )
    return list(result.scalars().all())


async def add(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    origin: str,
    created_by_user_id: uuid.UUID | None = None,
) -> WidgetAllowedOrigin:
    row = WidgetAllowedOrigin(
        tenant_id=tenant_id,
        origin=origin,
        created_by_user_id=created_by_user_id,
    )
    session.add(row)
    await session.flush()
    return row


async def remove(session: AsyncSession, origin_id: uuid.UUID) -> bool:
    row = (
        await session.execute(
            select(WidgetAllowedOrigin).where(WidgetAllowedOrigin.id == origin_id)
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    await session.delete(row)
    await session.flush()
    return True


async def exists_for_tenant(
    session: AsyncSession, tenant_id: uuid.UUID, origin: str
) -> bool:
    """Whether ``origin`` is on ``tenant_id``'s allowlist.

    Retained for future use / admin tooling. As of feature 006 (Approach A) the
    request-time session and chat paths no longer call this — the customer
    allowlist governs embedding only (frame-ancestors), not token exchange.
    """
    result = await session.execute(
        select(WidgetAllowedOrigin.id).where(
            WidgetAllowedOrigin.tenant_id == tenant_id,
            WidgetAllowedOrigin.origin == origin,
        )
    )
    return result.first() is not None
