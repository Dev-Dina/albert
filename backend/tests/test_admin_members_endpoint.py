"""Contract tests for the /api/v1/admin/members endpoints (FR-050 exception 1.b–d).

Covers: list own ``member`` rows only; invite 201 + appears in list; duplicate
email → 409; weak password → 422; remove 200 + gone; not-found → 404;
self-remove → 409; tenant-bleed delete → 404; role mismatch (manager → 403).

A shared StaticPool in-memory SQLite engine is reset per test (the ``_state``
flag is cleared in ``setup_function`` so the first DB access of each test
re-seeds; later requests in the same test reuse the seeded data).
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes.admin_widgets import AdminIdentity, require_admin_identity
from app.auth.models import Role
from app.db.base import Base
from app.db.models.membership import TenantMembership
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.session import get_db
from app.main import app

client = TestClient(app)

_TABLES = ("users", "tenants", "tenant_memberships", "audit_logs")
_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
)
_SessionLocal = async_sessionmaker(bind=_ENGINE, class_=AsyncSession, expire_on_commit=False)

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()
ADMIN_A = uuid.uuid4()
MEMBER_A1 = uuid.uuid4()
MEMBER_B1 = uuid.uuid4()
MANAGER_ID = uuid.uuid4()

MEMBER_A1_EMAIL = "member.a1@example.com"
MEMBER_B1_EMAIL = "member.b1@example.com"

_state = {"ready": False}


async def _ensure_seeded(session: AsyncSession) -> None:
    if _state["ready"]:
        return
    conn = await session.connection()
    tables = [t for t in Base.metadata.sorted_tables if t.name in _TABLES]
    await conn.run_sync(lambda c: Base.metadata.drop_all(c, tables=tables))
    await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    session.add(Tenant(id=TENANT_A, name="Acme", slug="acme", status="active"))
    session.add(Tenant(id=TENANT_B, name="Beta", slug="beta", status="active"))
    session.add(User(id=ADMIN_A, email="admin.a@x.test", hashed_password="x", is_active=True))
    session.add(User(id=MEMBER_A1, email=MEMBER_A1_EMAIL, hashed_password="x", is_active=True))
    session.add(User(id=MEMBER_B1, email=MEMBER_B1_EMAIL, hashed_password="x", is_active=True))
    session.add(TenantMembership(id=uuid.uuid4(), tenant_id=TENANT_A, user_id=ADMIN_A, role=Role.tenant_admin.value))
    session.add(TenantMembership(id=uuid.uuid4(), tenant_id=TENANT_A, user_id=MEMBER_A1, role=Role.member.value))
    session.add(TenantMembership(id=uuid.uuid4(), tenant_id=TENANT_B, user_id=MEMBER_B1, role=Role.member.value))
    await session.commit()
    _state["ready"] = True


async def _override_get_db():
    async with _SessionLocal() as session:
        await _ensure_seeded(session)
        yield session


def _admin_headers() -> dict[str, str]:
    # 003's require_admin_identity also sets the Postgres RLS context
    # (set_config), which SQLite lacks — so override it directly with a
    # resolved AdminIdentity, mirroring 003's own admin tests.
    app.dependency_overrides[require_admin_identity] = lambda: AdminIdentity(
        user_id=ADMIN_A, tenant_id=TENANT_A
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
    _state["ready"] = False  # force a clean re-seed for each test


def teardown_function() -> None:
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_admin_identity, None)


def test_list_returns_only_own_tenant_members() -> None:
    response = client.get("/api/v1/admin/members", headers=_admin_headers())
    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["email"] == MEMBER_A1_EMAIL


def test_invite_creates_member_and_appears_in_list() -> None:
    new_email = "fresh.member@example.com"
    create = client.post(
        "/api/v1/admin/members",
        headers=_admin_headers(),
        json={"email": new_email, "password": "strong-pass-123"},
    )
    assert create.status_code == 201, create.text
    assert create.json()["email"] == new_email

    listing = client.get("/api/v1/admin/members", headers=_admin_headers())
    emails = {row["email"] for row in listing.json()}
    assert new_email in emails


def test_invite_duplicate_email_returns_409() -> None:
    response = client.post(
        "/api/v1/admin/members",
        headers=_admin_headers(),
        json={"email": MEMBER_A1_EMAIL, "password": "strong-pass-123"},
    )
    assert response.status_code == 409, response.text


def test_invite_weak_password_returns_422() -> None:
    response = client.post(
        "/api/v1/admin/members",
        headers=_admin_headers(),
        json={"email": "weakpw@example.com", "password": "short"},
    )
    assert response.status_code == 422, response.text


def test_remove_member_succeeds_and_is_gone() -> None:
    remove = client.delete(f"/api/v1/admin/members/{MEMBER_A1}", headers=_admin_headers())
    assert remove.status_code == 200, remove.text
    assert remove.json()["removed_user_id"] == str(MEMBER_A1)

    listing = client.get("/api/v1/admin/members", headers=_admin_headers())
    assert listing.json() == []


def test_remove_unknown_member_returns_404() -> None:
    response = client.delete(f"/api/v1/admin/members/{uuid.uuid4()}", headers=_admin_headers())
    assert response.status_code == 404


def test_self_remove_returns_409() -> None:
    response = client.delete(f"/api/v1/admin/members/{ADMIN_A}", headers=_admin_headers())
    assert response.status_code == 409


def test_tenant_bleed_delete_returns_404() -> None:
    # Admin A cannot delete tenant B's member — the WHERE clause filters by tenant.
    response = client.delete(f"/api/v1/admin/members/{MEMBER_B1}", headers=_admin_headers())
    assert response.status_code == 404


def test_manager_gets_403() -> None:
    response = client.get("/api/v1/admin/members", headers=_manager_headers())
    assert response.status_code == 403
