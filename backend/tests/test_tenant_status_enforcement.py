"""Tenant status enforcement (feature 009): suspended/erased tenants are locked out.

Covers the centralized status helper (``app/tenancy/status.py``) and the admin
principal-resolution gate (``resolve_current_user``). Login enforcement lives in
test_auth.py; the widget handshake + chat gates live in test_widget_status_lockout.py.

No DB — the two reads each helper issues are routed by a fake session.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.auth.models import Role
from app.auth.roles import resolve_current_user
from app.tenancy.status import is_tenant_active, user_has_active_tenant


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeUser:
    def __init__(self, platform_role: str | None = None) -> None:
        self.id = uuid.uuid4()
        self.email = "u@example.com"
        self.platform_role = platform_role


class _FakeMembership:
    def __init__(self, tenant_id: uuid.UUID, role: str = "tenant_admin") -> None:
        self.tenant_id = tenant_id
        self.role = role


class _Result:
    def __init__(self, *, rows=None, scalar=None, scalar_one=None) -> None:
        self._rows = rows or []
        self._scalar = scalar
        self._scalar_one = scalar_one

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._scalar_one


class _FakeDB:
    """Routes the three reads exercised here:
    - ``user_has_active_tenant`` → ``SELECT EXISTS(...)`` (``.scalar()``)
    - membership resolution     → ``SELECT ... FROM tenant_memberships`` (``.scalars().all()``)
    - ``is_tenant_active``       → ``SELECT tenants.status`` (``.scalar_one_or_none()``)
    """

    def __init__(self, *, rows=None, tenant_status="active", has_active=True) -> None:
        self._rows = rows or []
        self._tenant_status = tenant_status
        self._has_active = has_active

    async def execute(self, statement, *args, **kwargs):
        sql = str(statement).lower()
        if "exists" in sql:
            return _Result(scalar=self._has_active)
        if "tenant_memberships" in sql:
            return _Result(rows=self._rows)
        return _Result(scalar_one=self._tenant_status)


# ---------------------------------------------------------------------------
# is_tenant_active
# ---------------------------------------------------------------------------

async def test_is_tenant_active_true_for_active() -> None:
    assert await is_tenant_active(_FakeDB(tenant_status="active"), uuid.uuid4()) is True


@pytest.mark.parametrize("status", ["suspended", "erased", None])
async def test_is_tenant_active_false_for_non_active_or_missing(status) -> None:
    assert await is_tenant_active(_FakeDB(tenant_status=status), uuid.uuid4()) is False


# ---------------------------------------------------------------------------
# user_has_active_tenant
# ---------------------------------------------------------------------------

async def test_user_has_active_tenant_true() -> None:
    assert await user_has_active_tenant(_FakeDB(has_active=True), uuid.uuid4()) is True


async def test_user_has_active_tenant_false() -> None:
    assert await user_has_active_tenant(_FakeDB(has_active=False), uuid.uuid4()) is False


# ---------------------------------------------------------------------------
# resolve_current_user status gate (FR-011, FR-014, FR-016)
# ---------------------------------------------------------------------------

async def test_resolve_blocks_tenant_scoped_user_on_non_active_tenant() -> None:
    tid = uuid.uuid4()
    db = _FakeDB(rows=[_FakeMembership(tid, "tenant_admin")], tenant_status="suspended")
    with pytest.raises(HTTPException) as exc:
        await resolve_current_user(_FakeUser(platform_role=None), db)
    assert exc.value.status_code == 403
    # Same shape as the "no role" refusal — no suspended/erased disclosure (FR-016).
    assert exc.value.detail == "No role assigned."


async def test_resolve_allows_active_tenant() -> None:
    tid = uuid.uuid4()
    db = _FakeDB(rows=[_FakeMembership(tid, "tenant_admin")], tenant_status="active")
    current = await resolve_current_user(_FakeUser(platform_role=None), db)
    assert current.role is Role.tenant_admin
    assert current.tenant_id == tid


async def test_resolve_platform_manager_exempt_from_status() -> None:
    # erased tenant status in the DB is irrelevant: a manager holds no tenant context.
    db = _FakeDB(rows=[], tenant_status="erased")
    current = await resolve_current_user(_FakeUser(platform_role="tenant_manager"), db)
    assert current.role is Role.tenant_manager
    assert current.tenant_id is None
