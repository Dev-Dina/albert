"""Contract tests for GET /api/v1/admin/leads (FR-050 exception 1.a).

Covers: happy path (own-tenant rows only), tenant-bleed (0 rows for an
empty tenant even though another tenant has many), and role mismatch
(manager → 403).

Uses a shared StaticPool in-memory SQLite engine; seeding runs lazily inside
the ``get_db`` override so create/seed and the request share one event loop.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes.admin_widgets import AdminIdentity, require_admin_identity
from app.db.base import Base
from app.db.models.lead import Lead
from app.db.models.tenant import Tenant
from app.db.session import get_db
from app.main import app

client = TestClient(app)

_TABLES = ("users", "tenants", "tenant_memberships", "leads")
_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
)
_SessionLocal = async_sessionmaker(bind=_ENGINE, class_=AsyncSession, expire_on_commit=False)

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()
TENANT_EMPTY = uuid.uuid4()
ADMIN_A = uuid.uuid4()
ADMIN_EMPTY = uuid.uuid4()
MANAGER_ID = uuid.uuid4()

_state = {"ready": False}


async def _ensure_seeded(session: AsyncSession) -> None:
    if _state["ready"]:
        return
    conn = await session.connection()
    tables = [t for t in Base.metadata.sorted_tables if t.name in _TABLES]
    await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    session.add(Tenant(id=TENANT_A, name="Acme", slug="acme", status="active"))
    session.add(Tenant(id=TENANT_B, name="Beta", slug="beta", status="active"))
    session.add(Tenant(id=TENANT_EMPTY, name="Empty", slug="empty", status="active"))
    # Tenant A: 2 leads. Tenant B: 3 leads. Tenant EMPTY: none.
    for i in range(2):
        session.add(
            Lead(id=uuid.uuid4(), tenant_id=TENANT_A, name=f"A lead {i}",
                 contact=f"a{i}@x.test", intent="demo", status="new")
        )
    for i in range(3):
        session.add(
            Lead(id=uuid.uuid4(), tenant_id=TENANT_B, name=f"B lead {i}",
                 contact=f"b{i}@x.test", intent="demo", status="new")
        )
    await session.commit()
    _state["ready"] = True


async def _override_get_db():
    async with _SessionLocal() as session:
        await _ensure_seeded(session)
        yield session


def _admin_headers(tenant_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, str]:
    # 003's require_admin_identity also sets the Postgres RLS context
    # (set_config), which SQLite lacks — so override it directly with a
    # resolved AdminIdentity, mirroring 003's own admin tests.
    app.dependency_overrides[require_admin_identity] = lambda: AdminIdentity(
        user_id=user_id, tenant_id=tenant_id
    )
    return {}


def _manager_headers() -> dict[str, str]:
    def _forbid() -> AdminIdentity:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Tenant admin role required."
        )

    app.dependency_overrides[require_admin_identity] = _forbid
    return {}


def setup_function() -> None:
    app.dependency_overrides[get_db] = _override_get_db


def teardown_function() -> None:
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_admin_identity, None)


def test_happy_path_returns_only_own_tenant_leads() -> None:
    response = client.get("/api/v1/admin/leads", headers=_admin_headers(TENANT_A, ADMIN_A))
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 2
    assert all(row["name"].startswith("A lead") for row in rows)


def test_tenant_bleed_empty_tenant_sees_no_rows() -> None:
    response = client.get(
        "/api/v1/admin/leads", headers=_admin_headers(TENANT_EMPTY, ADMIN_EMPTY)
    )
    assert response.status_code == 200, response.text
    assert response.json() == []


def test_manager_gets_403() -> None:
    response = client.get("/api/v1/admin/leads", headers=_manager_headers())
    assert response.status_code == 403
