import uuid

import pytest
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app.auth.models import Role
from app.auth.roles import CurrentUser, assert_not_tenant_manager_content_read
from app.auth.users import create_access_token, hash_password, verify_password
from app.db.models.user import User
from app.db.session import get_db
from app.deps import _resolve_tenant_from_token
from app.main import app

client = TestClient(app)

_USER_ID = uuid.uuid4()
_PASSWORD = "admin123"


def _make_user() -> User:
    return User(
        id=_USER_ID,
        email="admin@example.com",
        hashed_password=hash_password(_PASSWORD),
        is_active=True,
        platform_role="tenant_manager",
    )


class _FakeScalars:
    """Stand-in for Result.scalars(); current login reads memberships via .first()."""

    def first(self) -> object:
        return None  # no membership → login resolves to the default member role

    def all(self) -> list:
        return []


class _FakeResult:
    def __init__(self, obj: object) -> None:
        self._obj = obj

    def scalar_one_or_none(self) -> object:
        return self._obj

    def scalars(self) -> "_FakeScalars":
        return _FakeScalars()


class _FakeSession:
    """Minimal stand-in for AsyncSession: returns a fixed user for any query."""

    def __init__(self, user: object) -> None:
        self._user = user

    async def execute(self, *args: object, **kwargs: object) -> _FakeResult:
        return _FakeResult(self._user)


def _override_db(user: object):
    async def _get_db():
        yield _FakeSession(user)

    return _get_db


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_tenant_manager_cannot_read_tenant_content() -> None:
    """A4 checkpoint: assert_not_tenant_manager_content_read blocks managers with 403.

    Tests the explicit guard that every content-read handler must call.
    Tenant-scoped roles (admin, member) must pass cleanly.
    """
    manager = CurrentUser(user_id=None, role=Role.tenant_manager, tenant_id=None)
    with pytest.raises(HTTPException) as exc_info:
        assert_not_tenant_manager_content_read(manager, "conversations")
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    for allowed_role in (Role.tenant_admin, Role.member):
        non_manager = CurrentUser(user_id=None, role=allowed_role, tenant_id=uuid.uuid4())
        assert_not_tenant_manager_content_read(non_manager, "conversations")  # must not raise


@pytest.mark.asyncio
async def test_manager_token_returns_403_on_tenant_scope() -> None:
    """A4 checkpoint: a manager JWT (no tenant_id claim) is rejected 403 by tenant_scope.

    _resolve_tenant_from_token — the inner function that tenant_scope calls —
    raises HTTP 403 when the token carries no tenant_id claim, which is always
    the case for tenant_manager tokens.
    """
    token = create_access_token(
        user_id=_USER_ID,
        email="manager@example.com",
        role=Role.tenant_manager,
    )
    creds = HTTPAuthorizationCredentials(scheme="bearer", credentials=token)
    with pytest.raises(HTTPException) as exc_info:
        await _resolve_tenant_from_token(creds)
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


def test_three_roles_only() -> None:
    """A4 checkpoint: exactly three roles exist — no additions, no removals."""
    assert set(Role) == {Role.tenant_manager, Role.tenant_admin, Role.member}
    assert {r.value for r in Role} == {"tenant_manager", "tenant_admin", "member"}


def test_hash_verifies_correct_password() -> None:
    hashed = hash_password(_PASSWORD)
    assert verify_password(_PASSWORD, hashed)


def test_hash_rejects_wrong_password() -> None:
    hashed = hash_password(_PASSWORD)
    assert not verify_password("wrong-password", hashed)


def test_login_success_returns_bearer_token() -> None:
    app.dependency_overrides[get_db] = _override_db(_make_user())
    response = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": _PASSWORD},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_wrong_password_returns_401() -> None:
    app.dependency_overrides[get_db] = _override_db(_make_user())
    response = client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_me_without_token_returns_401() -> None:
    response = client.get("/auth/me")
    assert response.status_code == 401


def test_me_with_valid_token_returns_user() -> None:
    app.dependency_overrides[get_db] = _override_db(_make_user())
    token = create_access_token(
        user_id=_USER_ID,
        email="admin@example.com",
        role=Role.tenant_manager,
    )
    response = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(_USER_ID)
    assert body["email"] == "admin@example.com"
    assert body["role"] == "tenant_manager"
    assert body["is_active"] is True
