"""Role-based access enforcement.

FastAPI dependencies and guard functions that enforce the three-role model.
Key invariant: ``tenant_manager`` has lifecycle + aggregate power only.
It MUST NOT gain read access to tenant conversations, leads, messages, or
CMS content under any code path.

The guard functions in this module are the single chokepoint for that check.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.models import Role
from app.auth.users import decode_access_token, get_role, get_tenant_id, get_user_id

_bearer = HTTPBearer(auto_error=True)


# ---------------------------------------------------------------------------
# Internal: decode + validate token → CurrentUser
# ---------------------------------------------------------------------------

class CurrentUser:
    """Resolved, verified identity for the current request."""

    def __init__(
        self,
        user_id: uuid.UUID | None,
        role: Role,
        tenant_id: uuid.UUID | None,
    ) -> None:
        self.user_id = user_id
        self.role = role
        self.tenant_id = tenant_id

    @property
    def is_tenant_manager(self) -> bool:
        return self.role == Role.tenant_manager

    @property
    def is_tenant_admin(self) -> bool:
        return self.role == Role.tenant_admin

    @property
    def is_member(self) -> bool:
        return self.role == Role.member


async def _current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Security(_bearer)],
) -> CurrentUser:
    """Decode the bearer token and return a verified CurrentUser.

    Raises HTTP 401 on invalid/expired token.
    """
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    role = get_role(payload)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token carries no valid role.",
        )
    return CurrentUser(
        user_id=get_user_id(payload),
        role=role,
        tenant_id=get_tenant_id(payload),
    )


# ---------------------------------------------------------------------------
# Exported dependencies — use these in route signatures
# ---------------------------------------------------------------------------

CurrentUserDep = Annotated[CurrentUser, Depends(_current_user)]


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

    Call this guard at the top of any handler that returns conversations,
    messages, leads, or CMS content — to make the no-content-read rule
    explicit and testable in one place.

    ``resource`` is a human-readable label for error/audit messages, e.g.
    "conversations", "leads", "cms_pages".
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
