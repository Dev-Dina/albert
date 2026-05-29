"""Isolation eval (Phase 6.5A): the runtime app role can execute the widget lookup.

Widget token exchange resolves a widget's tenant BEFORE any tenant context exists,
via the SECURITY DEFINER function ``lookup_widget_by_public_id(text)`` (migration
0004). PUBLIC execute is revoked; the runtime role ``albert_app`` (non-superuser,
NOBYPASSRLS) must hold an explicit GRANT EXECUTE, or ``/api/v1/widget/session``
500s with "permission denied for function lookup_widget_by_public_id".

These tests connect as the migration/superuser role and ``SET ROLE albert_app``
to exercise the exact runtime privilege check — the same pattern the other
isolation evals use. Requires a live Postgres with migrations applied:

    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/albert \
        uv run pytest ../evals/isolation/test_widget_lookup_grant.py -v
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

_TEST_DB_URL = settings.database_url or "postgresql+asyncpg://postgres:postgres@postgres:5432/albert"
_APP_ROLE = "albert_app"


@pytest_asyncio.fixture
async def engine():
    e = create_async_engine(_TEST_DB_URL, future=True, pool_size=2, max_overflow=0)
    try:
        yield e
    finally:
        await e.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncSession:
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
        await session.rollback()


async def _seed_widget(db: AsyncSession, tenant_id: uuid.UUID, public_id: str) -> uuid.UUID:
    """Seed a tenant + enabled widget as the superuser (RLS bypassed). Rolled back."""
    widget_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO tenants (id, name, slug, status) VALUES "
            "(:tid, 'Lookup Co', :slug, 'active') ON CONFLICT (id) DO NOTHING"
        ),
        {"tid": str(tenant_id), "slug": f"lookup-{tenant_id.hex[:8]}"},
    )
    await db.execute(
        text(
            "INSERT INTO widgets (id, tenant_id, public_widget_id, name, theme, greeting, status) "
            "VALUES (:id, :tid, :pid, 'w', '{}', '', 'enabled')"
        ),
        {"id": str(widget_id), "tid": str(tenant_id), "pid": public_id},
    )
    return widget_id


@pytest.mark.asyncio
async def test_app_role_can_execute_widget_lookup(db: AsyncSession) -> None:
    """albert_app can EXECUTE lookup_widget_by_public_id and gets the right row."""
    tenant_id = uuid.uuid4()
    public_id = "Zz" + uuid.uuid4().hex[:20]  # 22-char base62-ish public id
    widget_id = await _seed_widget(db, tenant_id, public_id)

    await db.execute(text(f"SET ROLE {_APP_ROLE}"))
    try:
        row = (
            await db.execute(
                text(
                    "SELECT widget_id, tenant_id, status "
                    "FROM lookup_widget_by_public_id(:pid)"
                ).bindparams(pid=public_id)
            )
        ).first()
    finally:
        await db.execute(text("RESET ROLE"))

    assert row is not None, "app role got no row — GRANT EXECUTE likely missing"
    assert row[0] == widget_id
    assert row[1] == tenant_id
    assert row[2] == "enabled"
    await db.rollback()


@pytest.mark.asyncio
async def test_app_role_lookup_unknown_id_returns_no_row(db: AsyncSession) -> None:
    """An unknown public id resolves to zero rows (no error) under the app role."""
    await db.execute(text(f"SET ROLE {_APP_ROLE}"))
    try:
        rows = (
            await db.execute(
                text(
                    "SELECT widget_id FROM lookup_widget_by_public_id(:pid)"
                ).bindparams(pid="does-not-exist-000000")
            )
        ).fetchall()
    finally:
        await db.execute(text("RESET ROLE"))
    assert rows == []
    await db.rollback()


@pytest.mark.asyncio
async def test_public_execute_on_widget_lookup_is_revoked(db: AsyncSession) -> None:
    """PUBLIC must not retain EXECUTE — only explicitly-granted roles may call it."""
    has_public = (
        await db.execute(
            text("SELECT has_function_privilege('public', 'lookup_widget_by_public_id(text)', 'EXECUTE')")
        )
    ).scalar_one()
    assert has_public is False, "PUBLIC should not have EXECUTE on the widget lookup"

    has_app = (
        await db.execute(
            text(
                "SELECT has_function_privilege(:role, 'lookup_widget_by_public_id(text)', 'EXECUTE')"
            ).bindparams(role=_APP_ROLE)
        )
    ).scalar_one()
    assert has_app is True, f"{_APP_ROLE} must have EXECUTE on the widget lookup"
    await db.rollback()
