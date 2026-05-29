"""Members repository — tenant-scoped reads/writes over ``tenant_memberships``.

The Members page manages only ``role='member'`` rows (the existing
``Role.member`` value); ``tenant_admin`` rows are managed by the platform
manager surface and are never touched here. Every query pins
``TenantMembership.tenant_id`` to the caller's resolved tenant.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role
from app.db.models.membership import TenantMembership
from app.db.models.user import User


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    """Return the platform user with this email, if any."""
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def list_members_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
) -> list[tuple[TenantMembership, str]]:
    """Return ``(membership, email)`` pairs for this tenant's members.

    Filters ``role == 'member'`` and scopes by ``tenant_id``; joins
    ``users.email`` for display. Ordered oldest-first for a stable list.
    """
    query = (
        select(TenantMembership, User.email)
        .join(User, User.id == TenantMembership.user_id)
        .where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.role == Role.member.value,
        )
        .order_by(TenantMembership.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(query)
    return [(row[0], row[1]) for row in result.all()]


async def get_member(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> TenantMembership | None:
    """Return the ``role='member'`` membership for ``(tenant_id, user_id)``.

    Returns ``None`` for a non-member or a row belonging to another tenant —
    the WHERE clause is what makes a cross-tenant delete surface as 404.
    """
    result = await session.execute(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user_id,
            TenantMembership.role == Role.member.value,
        )
    )
    return result.scalar_one_or_none()


async def add_member(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> TenantMembership:
    """Insert a ``role='member'`` membership row for this tenant."""
    membership = TenantMembership(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        role=Role.member.value,
    )
    session.add(membership)
    await session.flush()
    # Load the server-default created_at so the response can render it.
    await session.refresh(membership)
    return membership


async def remove_member(
    session: AsyncSession, membership: TenantMembership
) -> None:
    """Delete a membership row; the underlying ``User`` row is preserved."""
    await session.delete(membership)
    await session.flush()
