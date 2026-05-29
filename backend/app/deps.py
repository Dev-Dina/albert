"""FastAPI dependencies for per-request tenant scoping.

The ``tenant_scope`` dependency is the single authoritative entry point for
resolving and activating a tenant context.  Every route that touches a
tenant-owned table must declare it (or use ``get_tenant_db`` with a
membership-resolved tenant id).

Security rule: tenant_id is NEVER read from the request body or query params.
It is resolved from the verified user's ``tenant_memberships`` (see
``app.auth.roles``), never trusting a client-supplied tenant identity.  Platform
managers have no membership and are refused a tenant context here.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.roles import CurrentUser, get_current_user
from app.db.session import get_db
from app.ratelimit import check_rate_limit
from app.tenancy.rls import clear_tenant_context, set_tenant_context


async def tenant_scope(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AsyncGenerator[uuid.UUID, None]:
    """Set the RLS tenant context for the duration of this request.

    Yields the resolved tenant_id so routes can pass it to services.  Always
    clears the context in a finally block before the session returns to the pool.
    Platform managers (no tenant) are refused — they never gain tenant-content access.
    """
    if current.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant context required; platform managers have no tenant content access.",
        )
    await check_rate_limit(current.tenant_id)
    await set_tenant_context(db, current.tenant_id)
    try:
        yield current.tenant_id
    finally:
        await clear_tenant_context(db)


# Convenience type alias for route signatures.
TenantDep = Annotated[uuid.UUID, Depends(tenant_scope)]
