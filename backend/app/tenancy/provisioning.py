"""Tenant provisioning: create a tenant and invite its first admin.

Rules (from specs/role_model.md and OWNER_A_PLAN):
- Only ``tenant_manager`` may provision a tenant.
- The platform operator never logs into a tenant to set it up — the tenant
  configures itself from the first-admin invitation link.
- Every provisioning action is audit-logged with the actor's user_id.
- tenant_id is a server-generated UUID v4; clients never choose it.
"""

from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role
from app.auth.users import hash_password
from app.db.models.membership import TenantMembership
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.tenancy.audit import record_audit

logger = logging.getLogger(__name__)


class TenantNotFoundError(Exception):
    """Raised when the target tenant does not exist."""


class AdminNotFoundError(Exception):
    """Raised when the user is not an admin of the target tenant."""


class LastAdminError(Exception):
    """Raised when removing the last tenant_admin of a tenant."""


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    """Convert a business name to a URL-safe slug.

    Slugs are for display/admin URLs only — never used for authorization.
    """
    return _SLUG_RE.sub("-", name.strip().lower()).strip("-")


_MAX_SLUG_ATTEMPTS = 100


async def _unique_slug(db: AsyncSession, base: str) -> str:
    """Return ``base`` if unused, otherwise ``base-2``, ``base-3``, etc.

    Raises ValueError after _MAX_SLUG_ATTEMPTS to prevent a runaway loop
    when many tenants share the same base name.
    """
    slug = base
    counter = 2
    while counter <= _MAX_SLUG_ATTEMPTS + 1:
        result = await db.execute(select(Tenant).where(Tenant.slug == slug))
        if result.scalar_one_or_none() is None:
            return slug
        slug = f"{base}-{counter}"
        counter += 1
    raise ValueError(
        f"Could not generate a unique slug for {base!r} after {_MAX_SLUG_ATTEMPTS} attempts."
    )


async def provision_tenant(
    *,
    db: AsyncSession,
    actor_user_id: uuid.UUID,
    name: str,
    first_admin_email: str,
    first_admin_password: str,
) -> tuple[Tenant, User]:
    """Create a new tenant and its first tenant_admin user.

    Returns ``(tenant, admin_user)``.

    The actor must hold the ``tenant_manager`` role — enforced at the route
    layer via ``require_tenant_manager``; this function trusts the caller has
    already verified that.

    Does NOT send an invitation email — that integration is out of scope for
    this phase.  The caller is responsible for surfacing the credential to the
    admin via a secure channel.
    """
    if not name or not name.strip():
        raise ValueError("Tenant name must not be empty.")

    # Check for duplicate first-admin email before any DB writes.
    existing = await db.execute(select(User).where(User.email == first_admin_email))
    if existing.scalar_one_or_none() is not None:
        raise ValueError(f"A user with email {first_admin_email!r} already exists.")

    base_slug = _slugify(name)
    if not base_slug:
        raise ValueError(f"Tenant name {name!r} produces an empty slug after normalization.")
    slug = await _unique_slug(db, base_slug)

    tenant = Tenant(
        id=uuid.uuid4(),
        name=name,
        slug=slug,
        status="active",
    )
    db.add(tenant)
    await db.flush()

    admin_user = User(
        id=uuid.uuid4(),
        email=first_admin_email,
        hashed_password=hash_password(first_admin_password),
        is_active=True,
    )
    db.add(admin_user)
    await db.flush()

    membership = TenantMembership(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        user_id=admin_user.id,
        role=Role.tenant_admin.value,
    )
    db.add(membership)
    await db.flush()

    await record_audit(
        db=db,
        actor_user_id=actor_user_id,
        target_tenant_id=tenant.id,
        action="tenant.provision",
        meta={"tenant_name": name, "first_admin_user_id": str(admin_user.id)},
    )

    logger.info(
        "tenant.provisioned tenant_id=%s slug=%s by actor=%s",
        tenant.id,
        slug,
        actor_user_id,
    )
    return tenant, admin_user


async def add_tenant_admin(
    *,
    db: AsyncSession,
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    email: str,
    password: str,
) -> tuple[User, uuid.UUID]:
    """Add a new tenant_admin to an existing active tenant.

    Returns ``(new_admin_user, tenant_id)``.

    Guards:
    - Tenant must exist and have status ``active``.
    - Email must not already be registered on the platform.
    - The unique constraint on (tenant_id, user_id) prevents duplicate memberships.
    """
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise TenantNotFoundError(f"Tenant {tenant_id!r} not found.")
    if tenant.status != "active":
        raise ValueError(
            f"Tenant {tenant_id!r} has status {tenant.status!r} — can only add admins to active tenants."
        )

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise ValueError(f"A user with email {email!r} already exists.")

    admin_user = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password(password),
        is_active=True,
    )
    db.add(admin_user)
    await db.flush()

    membership = TenantMembership(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=admin_user.id,
        role=Role.tenant_admin.value,
    )
    db.add(membership)
    await db.flush()

    await record_audit(
        db=db,
        actor_user_id=actor_user_id,
        target_tenant_id=tenant_id,
        action="tenant.admin.add",
        meta={"affected_user_id": str(admin_user.id), "email": email},
    )

    logger.info(
        "tenant.admin.added tenant_id=%s new_admin=%s by actor=%s",
        tenant_id,
        admin_user.id,
        actor_user_id,
    )
    return admin_user, tenant_id


async def remove_tenant_admin(
    *,
    db: AsyncSession,
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> uuid.UUID:
    """Remove a tenant_admin from a tenant.

    Deletes the TenantMembership only — the User row is preserved.

    Guards:
    - The user must hold a tenant_admin membership for this tenant.
    - Cannot remove the last remaining admin (tenant must always have at least one).
    """
    membership_result = await db.execute(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user_id,
            TenantMembership.role == Role.tenant_admin.value,
        )
    )
    membership = membership_result.scalar_one_or_none()
    if membership is None:
        raise AdminNotFoundError(
            f"User {user_id!r} is not a tenant_admin of tenant {tenant_id!r}."
        )

    count_result = await db.execute(
        select(func.count()).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.role == Role.tenant_admin.value,
        )
    )
    admin_count = count_result.scalar_one()
    if admin_count <= 1:
        raise LastAdminError(
            f"Cannot remove the last admin from tenant {tenant_id!r}."
        )

    await db.delete(membership)
    await db.flush()

    await record_audit(
        db=db,
        actor_user_id=actor_user_id,
        target_tenant_id=tenant_id,
        action="tenant.admin.remove",
        meta={"affected_user_id": str(user_id)},
    )

    logger.info(
        "tenant.admin.removed tenant_id=%s removed_user=%s by actor=%s",
        tenant_id,
        user_id,
        actor_user_id,
    )
    return user_id


async def create_platform_manager(
    *,
    db: AsyncSession,
    actor_user_id: uuid.UUID,
    email: str,
    password: str,
) -> User:
    """Create a new user and assign them the tenant_manager (platform-level) role.

    Guards:
    - Email must not already be registered on the platform.

    The new manager's TenantMembership has tenant_id=None — they are
    platform-scoped and their JWT will carry no tenant_id claim.
    """
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise ValueError(f"A user with email {email!r} already exists.")

    manager_user = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password(password),
        is_active=True,
    )
    db.add(manager_user)
    await db.flush()

    membership = TenantMembership(
        id=uuid.uuid4(),
        tenant_id=None,
        user_id=manager_user.id,
        role=Role.tenant_manager.value,
    )
    db.add(membership)
    await db.flush()

    await record_audit(
        db=db,
        actor_user_id=actor_user_id,
        target_tenant_id=None,
        action="platform.manager.add",
        meta={"new_manager_user_id": str(manager_user.id), "email": email},
    )

    logger.info(
        "platform.manager.added new_manager=%s by actor=%s",
        manager_user.id,
        actor_user_id,
    )
    return manager_user


async def suspend_tenant(
    *,
    db: AsyncSession,
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> Tenant:
    """Mark a tenant as suspended.  Does not delete data."""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise ValueError(f"Tenant {tenant_id!r} not found.")
    if tenant.status == "erased":
        raise ValueError(f"Tenant {tenant_id!r} is erased and cannot be suspended.")
    if tenant.status == "suspended":
        raise ValueError(f"Tenant {tenant_id!r} is already suspended.")

    tenant.status = "suspended"
    await db.flush()

    await record_audit(
        db=db,
        actor_user_id=actor_user_id,
        target_tenant_id=tenant_id,
        action="tenant.suspend",
    )

    logger.info("tenant.suspended tenant_id=%s by actor=%s", tenant_id, actor_user_id)
    return tenant


async def reactivate_tenant(
    *,
    db: AsyncSession,
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> Tenant:
    """Lift a suspension and return the tenant to active status."""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise ValueError(f"Tenant {tenant_id!r} not found.")
    if tenant.status == "erased":
        raise ValueError(f"Tenant {tenant_id!r} is erased and cannot be reactivated.")
    if tenant.status == "active":
        raise ValueError(f"Tenant {tenant_id!r} is already active.")

    tenant.status = "active"
    await db.flush()

    await record_audit(
        db=db,
        actor_user_id=actor_user_id,
        target_tenant_id=tenant_id,
        action="tenant.reactivate",
    )

    logger.info("tenant.reactivated tenant_id=%s by actor=%s", tenant_id, actor_user_id)
    return tenant
