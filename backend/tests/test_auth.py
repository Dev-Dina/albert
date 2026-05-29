"""Auth contract: JSON /auth/login (fastapi-users-issued JWT) + /auth/me.

No DB — the fastapi-users UserManager and current-user dependency are overridden
with stubs so the test exercises the route contract (credential check delegated
to fastapi-users, JWT issued by the JWT strategy) without a live database.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app.auth.fastapi_users import current_active_user, get_user_manager
from app.auth.models import Role
from app.auth.password import hash_password, verify_password
from app.auth.roles import CurrentUser, assert_not_tenant_manager_content_read
from app.main import app


client = TestClient(app)

_USER_ID = uuid.uuid4()
_EMAIL = "admin-acme@example.com"
_PASSWORD = "admin123"


class _FakeUser:
    def __init__(self, *, is_active: bool = True, platform_role: str | None = None) -> None:
        self.id = _USER_ID
        self.email = _EMAIL
        self.is_active = is_active
        self.platform_role = platform_role


class _StubUserManager:
    """Minimal stand-in for fastapi-users UserManager.authenticate()."""

    def __init__(self, user: _FakeUser | None) -> None:
        self._user = user

    async def authenticate(self, credentials) -> _FakeUser | None:
        if self._user is None:
            return None
        if credentials.username == _EMAIL and credentials.password == _PASSWORD:
            return self._user
        return None


def _override_user_manager(user: _FakeUser | None):
    def _dep():
        return _StubUserManager(user)

    return _dep


def teardown_function() -> None:
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Password hashing (the shared fastapi-users helper)
# ---------------------------------------------------------------------------

def test_hash_verifies_correct_password() -> None:
    assert verify_password(_PASSWORD, hash_password(_PASSWORD))


def test_hash_rejects_wrong_password() -> None:
    assert not verify_password("wrong-password", hash_password(_PASSWORD))


# ---------------------------------------------------------------------------
# /auth/login — JSON adapter over fastapi-users
# ---------------------------------------------------------------------------

def test_login_success_returns_bearer_token() -> None:
    app.dependency_overrides[get_user_manager] = _override_user_manager(_FakeUser())
    response = client.post("/auth/login", json={"email": _EMAIL, "password": _PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_wrong_password_returns_401() -> None:
    app.dependency_overrides[get_user_manager] = _override_user_manager(_FakeUser())
    response = client.post("/auth/login", json={"email": _EMAIL, "password": "nope"})
    assert response.status_code == 401


def test_login_inactive_user_returns_401() -> None:
    app.dependency_overrides[get_user_manager] = _override_user_manager(
        _FakeUser(is_active=False)
    )
    response = client.post("/auth/login", json={"email": _EMAIL, "password": _PASSWORD})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# /auth/me
# ---------------------------------------------------------------------------

def test_me_without_token_returns_401() -> None:
    assert client.get("/auth/me").status_code == 401


def test_me_with_valid_user_returns_identity() -> None:
    app.dependency_overrides[current_active_user] = lambda: _FakeUser(
        platform_role="tenant_manager"
    )
    response = client.get("/auth/me")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(_USER_ID)
    assert body["email"] == _EMAIL
    assert body["role"] == "tenant_manager"
    assert body["is_active"] is True


# ---------------------------------------------------------------------------
# Manager content-read guard (ported from main; adapted to 003's CurrentUser)
# ---------------------------------------------------------------------------

def test_tenant_manager_cannot_read_tenant_content() -> None:
    """``assert_not_tenant_manager_content_read`` blocks managers with 403.

    The explicit guard every content-read handler must call. Tenant-scoped
    roles (admin, member) must pass cleanly.
    """
    manager = CurrentUser(
        user_id=uuid.uuid4(), role=Role.tenant_manager, tenant_id=None,
        email="manager@example.com",
    )
    with pytest.raises(HTTPException) as exc_info:
        assert_not_tenant_manager_content_read(manager, "conversations")
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    for allowed_role in (Role.tenant_admin, Role.member):
        non_manager = CurrentUser(
            user_id=uuid.uuid4(), role=allowed_role, tenant_id=uuid.uuid4(),
            email="user@example.com",
        )
        # Must not raise.
        assert_not_tenant_manager_content_read(non_manager, "conversations")
