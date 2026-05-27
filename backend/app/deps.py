"""FastAPI dependencies for per-request tenant scoping.

The ``tenant_scope`` dependency is the single authoritative entry point for
resolving and activating a tenant context.  Every route that touches a
tenant-owned table must declare it.

Security rule: tenant_id is NEVER read from the request body, query params,
or any client-supplied field.  It is resolved exclusively from the verified
JWT bearer token (authenticated users) or the signed widget token (visitor
requests).  Trusting a body-supplied tenant_id is a one-line cross-tenant breach.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.users import decode_access_token
from app.db.session import get_db
from app.ratelimit import check_rate_limit
from app.tenancy.rls import clear_tenant_context, set_tenant_context

_bearer = HTTPBearer(auto_error=True)


async def _resolve_tenant_from_token(
    credentials: Annotated[HTTPAuthorizationCredentials, Security(_bearer)],
) -> uuid.UUID:
    """Decode the bearer token and return the verified tenant_id.

    Raises HTTP 401 if the token is missing, expired, or invalid.
    Raises HTTP 403 if the token carries no tenant claim (e.g. platform-only token).

    The token is the ONLY source of tenant identity.  Request body / query
    params are intentionally ignored.
    """
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    raw_tid = payload.get("tenant_id")
    if not raw_tid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token does not carry a tenant claim.",
        )
    try:
        return uuid.UUID(str(raw_tid))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token tenant_id is malformed.",
        )


async def tenant_scope(
    tenant_id: Annotated[uuid.UUID, Depends(_resolve_tenant_from_token)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AsyncGenerator[uuid.UUID, None]:
    """Set the RLS tenant context for the duration of this request.

    Yields the resolved tenant_id so routes can pass it to services.
    Always clears the context in a finally block before the session returns
    to the pool — belt-and-suspenders on top of the transaction-local guarantee.

    Usage in a route::

        @router.get("/conversations")
        async def list_convs(
            tenant_id: Annotated[uuid.UUID, Depends(tenant_scope)],
            db: Annotated[AsyncSession, Depends(get_db)],
        ):
            ...
    """
    await check_rate_limit(tenant_id)
    await set_tenant_context(db, tenant_id)
    try:
        yield tenant_id
    finally:
        await clear_tenant_context(db)


# Convenience type alias for route signatures.
TenantDep = Annotated[uuid.UUID, Depends(tenant_scope)]
