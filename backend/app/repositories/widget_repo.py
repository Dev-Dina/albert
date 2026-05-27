"""Widget repository — tenant-scoped CRUD plus the public-id lookup path.

All reads/writes via SQLAlchemy run under the tenant RLS context set by
``app.core.tenant_context``. The public-id lookup is the single exception:
it must resolve a tenant_id BEFORE a tenant context exists, so it calls the
``lookup_widget_by_public_id`` SECURITY DEFINER function created in migration
0003. The function returns only (widget_id, tenant_id, status).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.widget import Widget


@dataclass(frozen=True)
class PublicWidgetLookup:
    widget_id: uuid.UUID
    tenant_id: uuid.UUID
    status: str


async def get_by_public_id(
    session: AsyncSession, public_widget_id: str
) -> PublicWidgetLookup | None:
    """Resolve (widget_id, tenant_id, status) for a public id with no tenant context."""
    row = (
        await session.execute(
            text(
                "SELECT widget_id, tenant_id, status "
                "FROM lookup_widget_by_public_id(:pid)"
            ).bindparams(pid=public_widget_id)
        )
    ).first()
    if row is None:
        return None
    return PublicWidgetLookup(
        widget_id=row[0], tenant_id=row[1], status=row[2]
    )


async def get_by_id(session: AsyncSession, widget_id: uuid.UUID) -> Widget | None:
    return (
        await session.execute(select(Widget).where(Widget.id == widget_id))
    ).scalar_one_or_none()


async def list_by_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> list[Widget]:
    result = await session.execute(
        select(Widget).where(Widget.tenant_id == tenant_id).order_by(Widget.created_at)
    )
    return list(result.scalars().all())


async def create(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    public_widget_id: str,
    name: str,
    theme: dict[str, Any] | None = None,
    greeting: str = "",
    status: str = "enabled",
) -> Widget:
    widget = Widget(
        tenant_id=tenant_id,
        public_widget_id=public_widget_id,
        name=name,
        theme=theme or {},
        greeting=greeting,
        status=status,
    )
    session.add(widget)
    await session.flush()
    return widget


async def update(
    session: AsyncSession, widget: Widget, **fields: Any
) -> Widget:
    allowed = {"name", "theme", "greeting", "status"}
    for key, value in fields.items():
        if key not in allowed:
            raise ValueError(f"widget_repo.update: field {key!r} not updatable")
        setattr(widget, key, value)
    await session.flush()
    return widget
