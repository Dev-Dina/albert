"""Regression: seed_dev_user creates a usable admin-dashboard login (real DB).

Proves the dev seed produces exactly what ``/auth/login`` needs for the tenant
admin dashboard: an active ``admin-acme@example.com`` whose password verifies, with
a ``tenant_admin`` membership for the ``acme`` tenant (plus the platform manager).
Also asserts idempotency (rerun creates no duplicate membership).

Requires a live Postgres with migrations applied (run in the isolation suite). A
single test keeps all module-level ``AsyncSessionLocal`` use on one event loop.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import select

# backend/scripts/ is not a package — add it to the path to import the seeder.
_SCRIPTS = Path(__file__).resolve().parents[2] / "backend" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import seed_dev_user  

from app.auth.password import verify_password  
from app.db.models.membership import TenantMembership  
from app.db.models.tenant import Tenant  
from app.db.models.user import User  
from app.db.session import AsyncSessionLocal, async_engine  


@pytest.mark.asyncio
async def test_seed_creates_login_users_idempotently() -> None:
    try:
        await _run()
    finally:
        # Dispose the shared module-level engine on THIS test's event loop so a
        # sibling test (different loop) does not reuse a closed-loop connection.
        await async_engine.dispose()


async def _run() -> None:
    # Run twice — the seed must be idempotent (no duplicate users/memberships).
    await seed_dev_user.seed()
    await seed_dev_user.seed()

    async with AsyncSessionLocal() as session:
        # --- tenant admin (the admin-dashboard login) -------------------------
        admin = (
            await session.execute(select(User).where(User.email == seed_dev_user.ADMIN_EMAIL))
        ).scalar_one_or_none()
        assert admin is not None, "admin-acme user not created"
        assert admin.is_active is True
        assert verify_password(seed_dev_user.DEV_PASSWORD, admin.hashed_password or "")

        tenant = (
            await session.execute(select(Tenant).where(Tenant.slug == seed_dev_user.TENANT_SLUG))
        ).scalar_one()
        admin_memberships = (
            await session.execute(
                select(TenantMembership).where(
                    TenantMembership.user_id == admin.id,
                    TenantMembership.tenant_id == tenant.id,
                )
            )
        ).scalars().all()
        assert len(admin_memberships) == 1, "expected exactly one acme membership (idempotent)"
        assert admin_memberships[0].role == "tenant_admin"

        # --- platform manager -------------------------------------------------
        # The manager is platform-scoped: identified by users.platform_role only,
        # with NO tenant membership (memberships are strictly tenant-scoped).
        manager = (
            await session.execute(select(User).where(User.email == seed_dev_user.MANAGER_EMAIL))
        ).scalar_one_or_none()
        assert manager is not None
        assert manager.platform_role == "tenant_manager"
        assert verify_password(seed_dev_user.DEV_PASSWORD, manager.hashed_password or "")
        mgr_memberships = (
            await session.execute(
                select(TenantMembership).where(TenantMembership.user_id == manager.id)
            )
        ).scalars().all()
        assert mgr_memberships == [], "platform manager must have no tenant membership"
