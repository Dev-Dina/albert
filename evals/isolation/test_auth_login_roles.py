"""Auth + role acceptance against a real DB (brief §11).

Proves, end-to-end against Postgres + the seeded demo data:
  * fastapi-users verifies credentials and issues a JWT for admin-acme/admin123;
  * the seeded acme admin is NOT a platform manager and resolves to tenant_admin@acme;
  * the seeded manager is platform tenant_manager with no tenant;
  * a platform manager cannot obtain a tenant context (no tenant content access);
  * a wrong password is rejected.

Cross-tenant RLS isolation, pooled-connection context clearing, and widget-token
verification are covered by the sibling isolation/widget suites. Single async test
keeps all module-level ``AsyncSessionLocal`` use on one event loop.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy import select

# backend/scripts/ is not a package — add it to the path to import the seeder.
_SCRIPTS = Path(__file__).resolve().parents[2] / "backend" / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import seed_dev_user  

from app.api.deps import get_admin_tenant_id  # noqa: E402
from app.auth.fastapi_users import UserManager, auth_backend  # noqa: E402
from app.auth.models import Role  # noqa: E402
from app.auth.roles import resolve_current_user  # noqa: E402
from app.db.models.tenant import Tenant  # noqa: E402
from app.db.models.user import User  # noqa: E402
from app.db.session import AsyncSessionLocal, async_engine  # noqa: E402


@pytest.mark.asyncio
async def test_login_and_role_resolution_real_db() -> None:
    try:
        await _run()
    finally:
        # Dispose the shared module-level engine on THIS test's event loop so a
        # sibling test (different loop) does not reuse a closed-loop connection.
        await async_engine.dispose()


async def _run() -> None:
    await seed_dev_user.seed()

    async with AsyncSessionLocal() as session:
        admin = (
            await session.execute(select(User).where(User.email == seed_dev_user.ADMIN_EMAIL))
        ).scalar_one()
        manager = (
            await session.execute(select(User).where(User.email == seed_dev_user.MANAGER_EMAIL))
        ).scalar_one()
        acme = (
            await session.execute(select(Tenant).where(Tenant.slug == seed_dev_user.TENANT_SLUG))
        ).scalar_one()

        # Seeded acme admin is tenant-scoped (tenant_admin@acme), NOT a manager.
        assert admin.platform_role is None
        admin_principal = await resolve_current_user(admin, session)
        assert admin_principal.role is Role.tenant_admin
        assert admin_principal.tenant_id == acme.id

        # Seeded manager is platform tenant_manager with no tenant.
        assert manager.platform_role == "tenant_manager"
        mgr_principal = await resolve_current_user(manager, session)
        assert mgr_principal.role is Role.tenant_manager
        assert mgr_principal.tenant_id is None

        # A platform manager cannot obtain a tenant context (no content read).
        with pytest.raises(HTTPException) as exc:
            await get_admin_tenant_id(mgr_principal)
        assert exc.value.status_code == 403

        # Login: fastapi-users verifies credentials and the JWT strategy issues a token.
        user_manager = UserManager(SQLAlchemyUserDatabase(session, User))
        good = await user_manager.authenticate(
            OAuth2PasswordRequestForm(
                username=seed_dev_user.ADMIN_EMAIL, password=seed_dev_user.DEV_PASSWORD
            )
        )
        assert good is not None
        assert good.id == admin.id
        token = await auth_backend.get_strategy().write_token(good)
        assert token  # non-empty bearer token

        bad = await user_manager.authenticate(
            OAuth2PasswordRequestForm(username=seed_dev_user.ADMIN_EMAIL, password="wrong-pass")
        )
        assert bad is None
