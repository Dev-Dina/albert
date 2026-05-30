"""Leads repository — tenant-scoped reads for the tenant-admin Leads page.

The single entry point ``list_for_tenant`` always pins ``Lead.tenant_id`` to the
caller's resolved tenant (derived from the verified JWT at the route layer).
There is no path here that returns another tenant's leads.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

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


async def get_for_tenant(
    session: AsyncSession, *, tenant_id: uuid.UUID, lead_id: uuid.UUID
) -> Lead | None:
    """Fetch one lead for this tenant, or None (no cross-tenant disclosure)."""
    result = await session.execute(
        select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def update_status(
    session: AsyncSession, *, lead: Lead, new_status: str
) -> Lead:
    """Set the lead's status and stamp ``status_changed_at``.

    Caller is responsible for validating the transition and owning the
    transaction (does not commit).
    """
    lead.status = new_status
    lead.status_changed_at = datetime.now(timezone.utc)
    await session.flush()
    return lead
