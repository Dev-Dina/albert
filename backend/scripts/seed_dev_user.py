"""Idempotent local-dev login seed. NOT for production.

Creates the users the admin dashboard + platform flows need to log in. Auth is
handled by fastapi-users; role is resolved per request from the DB:
  * Platform manager:  manager@example.com / admin123
        users.platform_role='tenant_manager', NO tenant membership.
  * Demo tenant:        acme
  * Tenant admin:       admin-acme@example.com / admin123
        users.platform_role=NULL, membership(tenant_id=acme, role='tenant_admin').

Idempotent and repairs partial state (fills a missing membership / fixes a wrong
platform_role if the user already exists).

Run in the backend container (after `docker compose up -d --build backend`):

    docker compose exec -T backend python scripts/seed_dev_user.py

For the FULL widget demo (widget + allowed origin + Vault signing key + a second
tenant), use the canonical bootstrap profile instead:

    docker compose --profile bootstrap up bootstrap

`tenants`, `users`, and `tenant_memberships` are platform tables (no RLS), so this
runs cleanly as the non-superuser runtime role without a tenant context. Password
hashing uses the same fastapi-users helper the login flow verifies with. Dev
passwords are documented placeholders, never real secrets.
"""

import asyncio
import sys
import uuid
from pathlib import Path

# Make the backend package root importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.auth.models import Role
from app.auth.password import hash_password
from app.db.models.membership import TenantMembership 
from app.db.models.tenant import Tenant  
from app.db.models.user import User  
from app.db.session import AsyncSessionLocal  

DEV_PASSWORD = "admin123"  # local dev only — documented, never a real secret
MANAGER_EMAIL = "manager@example.com"
ADMIN_EMAIL = "admin-acme@example.com"
TENANT_SLUG = "acme"


async def _get_or_create_tenant(session, slug: str, name: str) -> Tenant:
    tenant = (
        await session.execute(select(Tenant).where(Tenant.slug == slug))
    ).scalar_one_or_none()
    if tenant is not None:
        return tenant
    tenant = Tenant(name=name, slug=slug, status="active")
    session.add(tenant)
    await session.flush()
    return tenant


async def _get_or_create_user(session, email: str, *, platform_role: str | None) -> User:
    user = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is not None:
        # Repair a wrong/missing platform_role on a pre-existing user.
        if user.platform_role != platform_role:
            user.platform_role = platform_role
        return user
    user = User(
        email=email,
        hashed_password=hash_password(DEV_PASSWORD),
        is_active=True,
        platform_role=platform_role,
    )
    session.add(user)
    await session.flush()
    return user


async def _ensure_membership(
    session, *, user_id: uuid.UUID, tenant_id: uuid.UUID, role: str
) -> None:
    """Create the tenant-scoped membership if absent (fills a gap for a pre-existing user)."""
    stmt = select(TenantMembership).where(
        TenantMembership.user_id == user_id,
        TenantMembership.tenant_id == tenant_id,
    )
    if (await session.execute(stmt)).scalar_one_or_none() is None:
        session.add(TenantMembership(user_id=user_id, tenant_id=tenant_id, role=role))


async def seed() -> dict[str, str]:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            tenant = await _get_or_create_tenant(session, TENANT_SLUG, TENANT_SLUG.capitalize())

            # Platform manager — platform_role only, no membership.
            await _get_or_create_user(
                session, MANAGER_EMAIL, platform_role=Role.tenant_manager.value
            )

            # Tenant admin — no platform role, tenant_admin membership for acme.
            admin = await _get_or_create_user(session, ADMIN_EMAIL, platform_role=None)
            await _ensure_membership(
                session, user_id=admin.id, tenant_id=tenant.id, role=Role.tenant_admin.value
            )
        return {
            "tenant_slug": tenant.slug,
            "manager_email": MANAGER_EMAIL,
            "admin_email": ADMIN_EMAIL,
            "password": DEV_PASSWORD,
        }


def main() -> int:
    info = asyncio.run(seed())
    print("Seeded dev login users (DEV ONLY):")
    print(f"  Platform manager: {info['manager_email']} / {info['password']}  (tenant_manager)")
    print(f"  Tenant admin:     {info['admin_email']} / {info['password']}  (tenant_admin for {info['tenant_slug']})")
    print("  Admin dashboard:  http://localhost:8501")
    print("  For the full widget demo: docker compose --profile bootstrap up bootstrap")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
