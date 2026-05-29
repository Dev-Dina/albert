"""Role-based access enforcement.

Identity is resolved per request from the database, never from the token
(fastapi-users JWTs carry only the user id):

- ``users.platform_role == 'tenant_manager'`` → platform **tenant_manager**
  (no tenant context; lifecycle + aggregate power only).
- otherwise the user's ``tenant_memberships`` (always tenant-scoped):
    * exactly one  → use it;
    * more than one → require an explicit ``X-Tenant-Id`` header verified against
      the user's memberships (never auto-pick);
    * none          → 403.

Key invariant: ``tenant_manager`` MUST NOT gain read access to tenant
conversations, leads, messages, or CMS content under any code path —
``assert_not_tenant_manager_content_read`` is the single chokepoint, and
``tenant_scope`` refuses managers a tenant context.

``users.is_superuser`` is fastapi-users-compat only and is NEVER consulted here.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.fastapi_users import current_active_user
from app.auth.models import Role
from app.db.models.membership import TenantMembership
from app.db.models.user import User
from app.db.session import get_db


class CurrentUser:
    """Resolved, verified identity for the current request."""

    def __init__(
        self,
        *,
        user_id: uuid.UUID,
        role: Role,
        tenant_id: uuid.UUID | None,
        email: str,
    ) -> None:
        self.user_id = user_id
        self.role = role
        self.tenant_id = tenant_id
        self.email = email

    @property
    def is_tenant_manager(self) -> bool:
        return self.role == Role.tenant_manager

    @property
    def is_tenant_admin(self) -> bool:
        return self.role == Role.tenant_admin

    @property
    def is_member(self) -> bool:
        return self.role == Role.member


async def resolve_current_user(
    user: User,
    db: AsyncSession,
    selected_tenant_id: uuid.UUID | None = None,
) -> CurrentUser:
    """Resolve role + tenant from the DB. ``tenant_memberships`` is a platform
    table (no RLS), so this runs without a tenant context."""
    if user.platform_role == Role.tenant_manager.value:
        return CurrentUser(
            user_id=user.id, role=Role.tenant_manager, tenant_id=None, email=user.email
        )

    rows = (
        await db.execute(
            select(TenantMembership).where(TenantMembership.user_id == user.id)
        )
    ).scalars().all()

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="No role assigned."
        )
    if len(rows) == 1:
        membership = rows[0]
    else:
        if selected_tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Multiple tenant memberships; specify X-Tenant-Id.",
            )
        membership = next(
            (r for r in rows if r.tenant_id == selected_tenant_id), None
        )
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a member of the requested tenant.",
            )

    try:
        role = Role(membership.role)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid role."
        ) from exc

    return CurrentUser(
        user_id=user.id, role=role, tenant_id=membership.tenant_id, email=user.email
    )


async def get_current_user(
    user: Annotated[User, Depends(current_active_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    x_tenant_id: Annotated[uuid.UUID | None, Header()] = None,
) -> CurrentUser:
    """Verified principal for the request. 401 without a valid token; 403/400
    per the resolution rule above."""
    return await resolve_current_user(user, db, x_tenant_id)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


async def require_tenant_manager(current: CurrentUserDep) -> CurrentUser:
    """Allow only ``tenant_manager``.  Raises 403 for all other roles."""
    if not current.is_tenant_manager:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant manager role required.",
        )
    return current


async def require_tenant_admin(current: CurrentUserDep) -> CurrentUser:
    """Allow only ``tenant_admin``.  Raises 403 for all other roles."""
    if not current.is_tenant_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant admin role required.",
        )
    return current


async def require_tenant_admin_or_manager(current: CurrentUserDep) -> CurrentUser:
    """Allow ``tenant_admin`` or ``tenant_manager``."""
    if current.role not in (Role.tenant_admin, Role.tenant_manager):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant admin or tenant manager role required.",
        )
    return current


# ---------------------------------------------------------------------------
# Content-read guard — the critical manager boundary
# ---------------------------------------------------------------------------

def assert_not_tenant_manager_content_read(current: CurrentUser, resource: str) -> None:
    """Raise if a tenant_manager is attempting to read tenant content.

    Call at the top of any handler returning conversations, messages, leads, or
    CMS content. ``resource`` is a human-readable label for error/audit messages.
    """
    if current.is_tenant_manager:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"tenant_manager may not read tenant {resource}. "
                "Lifecycle and aggregate access only."
            ),
        )


# Convenience type aliases
TenantManagerDep = Annotated[CurrentUser, Depends(require_tenant_manager)]
TenantAdminDep = Annotated[CurrentUser, Depends(require_tenant_admin)]
TenantAdminOrManagerDep = Annotated[CurrentUser, Depends(require_tenant_admin_or_manager)]
