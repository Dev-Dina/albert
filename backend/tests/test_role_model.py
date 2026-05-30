"""Role model: exactly three roles; manager platform-level; admin/member tenant-scoped.

No DB — exercises the Role enum and the DB-resolution rule in
``app.auth.roles.resolve_current_user`` with fakes. fastapi-users JWTs carry only
the user id, so role + tenant are resolved per request from the DB; these tests
pin that resolution logic. The widget "member" visitor case is proven against the
real per-tenant signed widget-session token.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.auth.models import PLATFORM_ROLES, TENANT_ROLES, Role
from app.auth.roles import resolve_current_user
from app.core.security import mint_widget_session_token, verify_widget_session_token


# ---------------------------------------------------------------------------
# Fakes for resolve_current_user(user, db, selected_tenant_id)
# ---------------------------------------------------------------------------

class _FakeUser:
    def __init__(self, platform_role: str | None) -> None:
        self.id = uuid.uuid4()
        self.email = "u@example.com"
        self.platform_role = platform_role


class _FakeMembership:
    def __init__(self, tenant_id: uuid.UUID, role: str) -> None:
        self.tenant_id = tenant_id
        self.role = role


class _FakeResult:
    def __init__(self, rows: list | None = None, scalar=None) -> None:
        self._rows = rows or []
        self._scalar = scalar

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._scalar


class _FakeDB:
    """Routes the two reads resolve_current_user issues: the membership SELECT
    (``.scalars().all()``) and the tenant-status SELECT (``.scalar_one_or_none()``).
    ``tenant_status`` defaults to active so existing resolution tests are unaffected.
    """

    def __init__(self, rows: list, tenant_status: str | None = "active") -> None:
        self._rows = rows
        self._tenant_status = tenant_status

    async def execute(self, statement, *args, **kwargs):
        if "tenant_memberships" in str(statement).lower():
            return _FakeResult(rows=self._rows)
        return _FakeResult(scalar=self._tenant_status)


# ---------------------------------------------------------------------------
# Role enum — exactly three, two levels
# ---------------------------------------------------------------------------

def test_exactly_three_roles() -> None:
    assert {r.value for r in Role} == {"tenant_manager", "tenant_admin", "member"}


def test_manager_is_platform_and_admin_member_are_tenant_scoped() -> None:
    assert Role.tenant_manager in PLATFORM_ROLES
    assert Role.tenant_manager not in TENANT_ROLES
    assert Role.tenant_admin in TENANT_ROLES
    assert Role.member in TENANT_ROLES


# ---------------------------------------------------------------------------
# DB resolution rule
# ---------------------------------------------------------------------------

async def test_manager_resolved_from_platform_role_no_membership() -> None:
    user = _FakeUser(platform_role="tenant_manager")
    current = await resolve_current_user(user, _FakeDB([]))  # rows ignored for manager
    assert current.role is Role.tenant_manager
    assert current.tenant_id is None  # platform-only → no tenant content access


async def test_single_tenant_admin_membership_is_used() -> None:
    tid = uuid.uuid4()
    user = _FakeUser(platform_role=None)
    current = await resolve_current_user(user, _FakeDB([_FakeMembership(tid, "tenant_admin")]))
    assert current.role is Role.tenant_admin
    assert current.tenant_id == tid


async def test_single_member_membership_is_tenant_scoped() -> None:
    tid = uuid.uuid4()
    user = _FakeUser(platform_role=None)
    current = await resolve_current_user(user, _FakeDB([_FakeMembership(tid, "member")]))
    assert current.role is Role.member
    assert current.tenant_id == tid


async def test_no_role_is_forbidden() -> None:
    with pytest.raises(HTTPException) as exc:
        await resolve_current_user(_FakeUser(platform_role=None), _FakeDB([]))
    assert exc.value.status_code == 403


async def test_multiple_memberships_require_explicit_tenant() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    rows = [_FakeMembership(a, "tenant_admin"), _FakeMembership(b, "member")]
    user = _FakeUser(platform_role=None)

    # No selection → 400 (never auto-pick).
    with pytest.raises(HTTPException) as exc:
        await resolve_current_user(user, _FakeDB(rows))
    assert exc.value.status_code == 400

    # Valid selection → that membership.
    current = await resolve_current_user(user, _FakeDB(rows), selected_tenant_id=b)
    assert current.tenant_id == b
    assert current.role is Role.member

    # Selection the user is not a member of → 403.
    with pytest.raises(HTTPException) as exc:
        await resolve_current_user(user, _FakeDB(rows), selected_tenant_id=uuid.uuid4())
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Member visitor — tenant-scoped via signed widget-session token
# ---------------------------------------------------------------------------

def test_member_widget_token_is_tenant_scoped() -> None:
    """An anonymous widget visitor ('member') is bound to exactly one tenant by a
    per-tenant signed token, verified with that tenant's key material."""
    tid = uuid.uuid4()
    wid = uuid.uuid4()
    key = b"dev-tenant-signing-key-bytes-!!!"
    token = mint_widget_session_token(
        tenant_id=tid,
        widget_id=wid,
        public_widget_id="Demo000000000000000000",
        origin="https://demo.example.com",
        key_version=1,
        key_material=key,
    )
    claims = verify_widget_session_token(token, key_material=key, expected_key_version=1)
    assert claims.tenant_id == tid
    assert claims.key_version == 1
