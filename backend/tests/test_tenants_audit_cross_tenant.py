"""Contract tests for GET /tenants/audit (FR-050 exception 3, cross-tenant).

Covers: happy path (rows from multiple tenants in one call), deterministic
``before_id`` pagination, admin → 403, and the content-exclusion guard
(response JSON keys ⊆ the audit allowlist).

A StaticPool in-memory SQLite engine is shared across sessions, and seeding is
done lazily inside the ``get_db`` override so the create/seed and the request
all run in the TestClient event loop (no cross-loop aiosqlite issues).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.models import Role
from app.auth.roles import CurrentUser, get_current_user
from app.db.base import Base
from app.db.models.audit_log import AuditLog
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.db.session import get_db
from app.main import app

client = TestClient(app)

_TABLES = ("users", "tenants", "audit_logs")
_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
)
_SessionLocal = async_sessionmaker(bind=_ENGINE, class_=AsyncSession, expire_on_commit=False)

MANAGER_ID = uuid.uuid4()
ACTOR_ID = uuid.uuid4()
TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()
_BASE_TIME = datetime(2026, 5, 1, 12, 0, 0)
_ENTRY_IDS = [uuid.uuid4() for _ in range(5)]

_ALLOWLIST = {
    "entry_id",
    "actor_user_id",
    "actor_email",
    "action",
    "target_tenant_id",
    "target_tenant_slug",
    "created_at",
    "meta",
}

_state = {"ready": False}


async def _ensure_seeded(session: AsyncSession) -> None:
    if _state["ready"]:
        return
    conn = await session.connection()
    tables = [t for t in Base.metadata.sorted_tables if t.name in _TABLES]
    await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    session.add(User(id=ACTOR_ID, email="actor@platform.test", hashed_password="x", is_active=True))
    session.add(Tenant(id=TENANT_A, name="Acme", slug="acme", status="active"))
    session.add(Tenant(id=TENANT_B, name="Beta", slug="beta", status="active"))
    # Five entries, alternating tenants, monotonically increasing created_at.
    for index, entry_id in enumerate(_ENTRY_IDS):
        session.add(
            AuditLog(
                id=entry_id,
                actor_user_id=ACTOR_ID,
                target_tenant_id=TENANT_A if index % 2 == 0 else TENANT_B,
                action="tenant.provision" if index % 2 == 0 else "tenant.suspend",
                meta={"note": "seed"},
                created_at=_BASE_TIME + timedelta(minutes=index),
            )
        )
    await session.commit()
    _state["ready"] = True


async def _override_get_db():
    async with _SessionLocal() as session:
        await _ensure_seeded(session)
        yield session


def _headers(role: Role, tenant_id: uuid.UUID | None = None) -> dict[str, str]:
    # 003 resolves role/tenant server-side, so override the resolved identity
    # dependency instead of minting a JWT.
    user_id = MANAGER_ID if role == Role.tenant_manager else uuid.uuid4()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=user_id, role=role, tenant_id=tenant_id, email="user@test.local"
    )
    return {}


def setup_function() -> None:
    app.dependency_overrides[get_db] = _override_get_db


def teardown_function() -> None:
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


def test_happy_path_returns_rows_from_multiple_tenants() -> None:
    response = client.get("/tenants/audit", headers=_headers(Role.tenant_manager))
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 5
    slugs = {row["target_tenant_slug"] for row in rows}
    assert slugs == {"acme", "beta"}
    # Newest-first ordering.
    timestamps = [row["created_at"] for row in rows]
    assert timestamps == sorted(timestamps, reverse=True)
    # Actor email is joined for display.
    assert all(row["actor_email"] == "actor@platform.test" for row in rows)


def test_before_id_pagination_is_deterministic() -> None:
    page1 = client.get(
        "/tenants/audit?limit=2", headers=_headers(Role.tenant_manager)
    ).json()
    assert len(page1) == 2
    cursor = page1[-1]["entry_id"]
    page2 = client.get(
        f"/tenants/audit?limit=2&before_id={cursor}",
        headers=_headers(Role.tenant_manager),
    ).json()
    assert len(page2) == 2
    ids1 = {row["entry_id"] for row in page1}
    ids2 = {row["entry_id"] for row in page2}
    assert ids1.isdisjoint(ids2)
    # Page 2 is strictly older than page 1.
    assert page2[0]["created_at"] < page1[-1]["created_at"]


def test_admin_role_gets_403() -> None:
    response = client.get(
        "/tenants/audit", headers=_headers(Role.tenant_admin, tenant_id=TENANT_A)
    )
    assert response.status_code == 403


def test_response_excludes_tenant_content() -> None:
    rows = client.get(
        "/tenants/audit", headers=_headers(Role.tenant_manager)
    ).json()
    assert rows
    for row in rows:
        assert set(row.keys()) <= _ALLOWLIST
