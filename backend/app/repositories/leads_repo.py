"""Leads repository — tenant-scoped reads for the tenant-admin Leads page.

The single entry point ``list_for_tenant`` always pins ``Lead.tenant_id`` to the
caller's resolved tenant (derived from the verified JWT at the route layer).
There is no path here that returns another tenant's leads.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.lead import Lead


async def list_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    since: datetime | None = None,
    until: datetime | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Lead]:
    """Return this tenant's leads, newest first.

    Always filters ``Lead.tenant_id == tenant_id`` regardless of the optional
    ``since``/``until``/``status`` filters — tenant scope is non-negotiable.
    """
    query = select(Lead).where(Lead.tenant_id == tenant_id)
    if since is not None:
        query = query.where(Lead.created_at >= since)
    if until is not None:
        query = query.where(Lead.created_at <= until)
    if status is not None:
        query = query.where(Lead.status == status)
    query = query.order_by(Lead.created_at.desc()).limit(limit).offset(offset)

    result = await session.execute(query)
    return list(result.scalars().all())
