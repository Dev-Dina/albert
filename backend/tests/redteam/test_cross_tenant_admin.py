"""Cross-tenant red-team for the admin data surfaces (feature 007).

Consolidated isolation gate for the three surfaces feature 007 adds: CMS content,
leads (status update), and escalations. Asserts that a Tenant B admin can never
read, modify, or enumerate a Tenant A record — every cross-tenant access returns
404 (no existence disclosure) or an empty list.

App-layer scoping is exercised here via the SQLite TestClient (RLS is a Postgres
feature); the **database-level** RLS fail-closed property (empty/wrong
`app.current_tenant` → no rows) is verified live against Postgres in
quickstart §0/§5 (T046).
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes.admin_widgets import AdminIdentity, require_admin_identity
from app.db.base import Base
from app.db.models.cms_page import CmsPage
from app.db.models.conversation import Conversation
from app.db.models.lead import Lead
from app.db.models.tenant import Tenant
from app.db.session import get_db
from app.main import app
from app.repositories import escalation_repo
from app.services import cms_service

_TABLES = ("tenants", "cms_pages", "leads", "conversations", "escalations")
_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
)
_SessionLocal = async_sessionmaker(bind=_ENGINE, class_=AsyncSession, expire_on_commit=False)

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()
ADMIN_B = uuid.uuid4()
PAGE_A = uuid.uuid4()
LEAD_A = uuid.uuid4()
CONV_A = uuid.uuid4()

_state = {"ready": False}


async def _ensure_seeded(session: AsyncSession) -> None:
    if _state["ready"]:
        return
    conn = await session.connection()
    tables = [t for t in Base.metadata.sorted_tables if t.name in _TABLES]
    await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    session.add(Tenant(id=TENANT_A, name="Acme", slug="acme", status="active"))
    session.add(Tenant(id=TENANT_B, name="Beta", slug="beta", status="active"))
    session.add(CmsPage(id=PAGE_A, tenant_id=TENANT_A, title="A", slug="a", body="secret", is_published=True))
    session.add(Lead(id=LEAD_A, tenant_id=TENANT_A, name="A", contact="a@x.test", intent="demo", status="new"))
    session.add(Conversation(id=CONV_A, tenant_id=TENANT_A, session_id=str(CONV_A), status="escalated"))
    await session.flush()
    await escalation_repo.upsert(
        session, tenant_id=TENANT_A, conversation_id=CONV_A, reason="A reason", summary="A summary"
    )
    await session.commit()
    _state["ready"] = True


async def _override_get_db():
    async with _SessionLocal() as session:
        await _ensure_seeded(session)
        yield session


def _setup() -> TestClient:
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[require_admin_identity] = lambda: AdminIdentity(
        user_id=ADMIN_B, tenant_id=TENANT_B
    )
    cms_service.schedule_reindex = lambda *a, **k: None  # type: ignore[assignment]
    cms_service.schedule_removal = lambda *a, **k: None  # type: ignore[assignment]
    return TestClient(app)


def _teardown() -> None:
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_admin_identity, None)


def test_tenant_b_cannot_reach_tenant_a_records() -> None:
    """Tenant B (acting admin) is denied every Tenant A record across surfaces."""
    client = _setup()
    try:
        # CMS content
        assert client.get(f"/api/v1/admin/cms/pages/{PAGE_A}").status_code == 404
        assert client.put(
            f"/api/v1/admin/cms/pages/{PAGE_A}", json={"body": "hijack"}
        ).status_code == 404
        assert client.delete(f"/api/v1/admin/cms/pages/{PAGE_A}").status_code == 404
        assert all(p["id"] != str(PAGE_A) for p in client.get("/api/v1/admin/cms/pages").json())

        # Leads (read + status update)
        assert client.get(f"/api/v1/admin/leads/{LEAD_A}").status_code == 404
        assert client.patch(
            f"/api/v1/admin/leads/{LEAD_A}", json={"status": "contacted"}
        ).status_code == 404

        # Escalations
        assert client.get(f"/api/v1/admin/escalations/{CONV_A}").status_code == 404
        assert client.get("/api/v1/admin/escalations").json() == []
    finally:
        _teardown()


if __name__ == "__main__":  # pragma: no cover
    test_tenant_b_cannot_reach_tenant_a_records()
    print("[REJECT] cross_tenant_admin: all Tenant A records denied to Tenant B")
