import uuid

from fastapi.testclient import TestClient

from app.core.security import create_access_token, hash_password, verify_password
from app.db.models.user import User
from app.db.session import get_db
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
    token = create_access_token(subject=str(_USER_ID), role="tenant_manager")
    response = client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(_USER_ID)
    assert body["email"] == "admin@example.com"
    assert body["role"] == "tenant_manager"
    assert body["is_active"] is True
