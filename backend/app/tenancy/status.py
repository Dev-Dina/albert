"""Tenant status enforcement helpers.

A tenant's lifecycle status (``active`` | ``suspended`` | ``erased``) is the single
authority for whether the tenant may be used. These helpers centralize the status read
so every enforcement point (login, admin principal resolution, widget handshake, chat
auth) applies the same rule and is auditable in one place.

Both helpers read the platform ``tenants`` table, which has no row-level security, so
they require no ``app.current_tenant`` context. Tenant identity is always supplied by the
caller from verified auth/session/widget context — never from client input.
"""

from __future__ import annotations

import uuid

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.membership import TenantMembership
from app.db.models.tenant import Tenant

#: The only tenant status that permits use of the product.
ACTIVE_STATUS = "active"


async def is_tenant_active(db: AsyncSession, tenant_id: uuid.UUID) -> bool:
    """Return ``True`` iff the tenant exists and its status is ``active``.

    A missing tenant returns ``False`` (treated as not usable), so callers fail closed.
    """
    result = await db.execute(select(Tenant.status).where(Tenant.id == tenant_id))
    status = result.scalar_one_or_none()
    return status == ACTIVE_STATUS


async def user_has_active_tenant(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """Return ``True`` iff the user has at least one membership in an active tenant.

    Used at login: a tenant-scoped user with no active tenant is refused, while a user
    who belongs to at least one active tenant (even if another of their tenants is
    suspended/erased) may still log in. Platform managers have no membership and are
    handled by the caller, not here.
    """
    stmt = select(
        exists().where(
            TenantMembership.user_id == user_id,
            TenantMembership.tenant_id == Tenant.id,
            Tenant.status == ACTIVE_STATUS,
        )
    )
    result = await db.execute(stmt)
    return bool(result.scalar())
