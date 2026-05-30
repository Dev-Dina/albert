"""Contract + cross-tenant tests for the tenant-admin CMS API (feature 007, US1).

Covers CRUD happy paths, body validation (FR-014), slug conflict (409), and
cross-tenant isolation (Tenant B cannot read/update/delete Tenant A pages → 404,
no existence disclosure).

Uses a shared StaticPool in-memory SQLite engine (mirrors test_admin_leads_endpoint).
The background re-index is stubbed to a no-op so tests never touch the real
embedder/Postgres.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes.admin_widgets import AdminIdentity, require_admin_identity
from app.db.base import Base
from app.db.models.tenant import Tenant
from app.db.session import get_db
from app.main import app
from app.services import cms_service

client = TestClient(app)

_TABLES = ("users", "tenants", "tenant_memberships", "cms_pages")
_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
)
_SessionLocal = async_sessionmaker(bind=_ENGINE, class_=AsyncSession, expire_on_commit=False)

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()
ADMIN_A = uuid.uuid4()
ADMIN_B = uuid.uuid4()

_state = {"ready": False}


async def _ensure_seeded(session: AsyncSession) -> None:
    if _state["ready"]:
        return
    conn = await session.connection()
    tables = [t for t in Base.metadata.sorted_tables if t.name in _TABLES]
    await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    session.add(Tenant(id=TENANT_A, name="Acme", slug="acme", status="active"))
    session.add(Tenant(id=TENANT_B, name="Beta", slug="beta", status="active"))
    await session.commit()
    _state["ready"] = True


async def _override_get_db():
    async with _SessionLocal() as session:
        await _ensure_seeded(session)
        yield session


def _as(tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    app.dependency_overrides[require_admin_identity] = lambda: AdminIdentity(
        user_id=user_id, tenant_id=tenant_id
    )


def setup_function() -> None:
    app.dependency_overrides[get_db] = _override_get_db
    # Stub background scheduling so tests never hit the real embedder/Postgres.
    cms_service.schedule_reindex = lambda *a, **k: None  # type: ignore[assignment]
    cms_service.schedule_removal = lambda *a, **k: None  # type: ignore[assignment]


def teardown_function() -> None:
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_admin_identity, None)


def _create(tenant: uuid.UUID, admin: uuid.UUID, **body) -> dict:
    _as(tenant, admin)
    payload = {"title": "Refund policy", "body": "We offer a 30-day refund."}
    payload.update(body)
    r = client.post("/api/v1/admin/cms/pages", json=payload)
    return r


# --- CRUD happy path --------------------------------------------------------


def test_create_then_get_and_list() -> None:
    r = _create(TENANT_A, ADMIN_A, title="FAQ", body="Distinctive A content")
    assert r.status_code == 201, r.text
    page = r.json()
    assert page["slug"] == "faq"
    assert page["is_published"] is True

    _as(TENANT_A, ADMIN_A)
    got = client.get(f"/api/v1/admin/cms/pages/{page['id']}")
    assert got.status_code == 200
    assert got.json()["body"] == "Distinctive A content"

    listed = client.get("/api/v1/admin/cms/pages")
    assert listed.status_code == 200
    assert any(p["id"] == page["id"] for p in listed.json())


def test_update_changes_body() -> None:
    page = _create(TENANT_A, ADMIN_A, title="Hours", body="Old hours").json()
    _as(TENANT_A, ADMIN_A)
    r = client.put(
        f"/api/v1/admin/cms/pages/{page['id']}", json={"body": "New hours"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["body"] == "New hours"


def test_delete_removes_page() -> None:
    page = _create(TENANT_A, ADMIN_A, title="Temp", body="bye").json()
    _as(TENANT_A, ADMIN_A)
    assert client.delete(f"/api/v1/admin/cms/pages/{page['id']}").status_code == 204
    assert client.get(f"/api/v1/admin/cms/pages/{page['id']}").status_code == 404


# --- validation -------------------------------------------------------------


def test_empty_body_rejected() -> None:
    r = _create(TENANT_A, ADMIN_A, title="X", body="   ")
    assert r.status_code == 422


def test_oversized_body_rejected() -> None:
    r = _create(TENANT_A, ADMIN_A, title="X", body="a" * 100_001)
    assert r.status_code == 422


def test_slug_conflict_returns_409() -> None:
    assert _create(TENANT_A, ADMIN_A, title="Dup", slug="dup").status_code == 201
    assert _create(TENANT_A, ADMIN_A, title="Dup2", slug="dup").status_code == 409


# --- cross-tenant isolation -------------------------------------------------


def test_cross_tenant_get_update_delete_are_404() -> None:
    page = _create(TENANT_A, ADMIN_A, title="Secret", body="Acme only").json()
    pid = page["id"]

    _as(TENANT_B, ADMIN_B)
    assert client.get(f"/api/v1/admin/cms/pages/{pid}").status_code == 404
    assert client.put(
        f"/api/v1/admin/cms/pages/{pid}", json={"body": "hijack"}
    ).status_code == 404
    assert client.delete(f"/api/v1/admin/cms/pages/{pid}").status_code == 404

    # Tenant B's list never includes Tenant A's page.
    listed = client.get("/api/v1/admin/cms/pages").json()
    assert all(p["id"] != pid for p in listed)
