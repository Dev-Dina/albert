"""Contract tests for the extended ``GET /auth/me`` (FR-050 exception 2).

Per ``contracts/backend_additions_contract.md`` §1 the response gains two
additive optional fields — ``tenant_id`` and ``tenant_name`` — populated for
``tenant_admin`` and ``null`` for ``tenant_manager``. ``tenant_name`` comes from
the ``tenants`` table via a lookup on the resolved ``tenant_id``, never the token.

Adapted to 003's auth: role + tenant are resolved server-side into a
``CurrentUser`` (``app.auth.roles.get_current_user``); these tests override that
dependency (so no real JWT is needed) plus ``get_db`` with a tiny fake session
whose ``execute().scalar_one_or_none()`` returns the tenant name.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.auth.models import Role
from app.auth.roles import CurrentUser, get_current_user
from app.db.session import get_db
from app.main import app

client = TestClient(app)

_TENANT_ID = uuid.uuid4()
_TENANT_NAME = "Acme Concierge Co"


def _manager() -> CurrentUser:
    return CurrentUser(
        user_id=uuid.uuid4(), role=Role.tenant_manager, tenant_id=None,
        email="manager@example.com",
    )


def _admin() -> CurrentUser:
    return CurrentUser(
        user_id=uuid.uuid4(), role=Role.tenant_admin, tenant_id=_TENANT_ID,
        email="admin@acme.test",
    )


class _FakeResult:
    """Stand-in for the tenant-name lookup; the handler calls ``scalar_one_or_none``."""

    def __init__(self, value: str | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> str | None:
        return self._value


class _FakeSession:
    def __init__(self, tenant_name: str | None) -> None:
        self._tenant_name = tenant_name

    async def execute(self, *args: object, **kwargs: object) -> _FakeResult:
        return _FakeResult(self._tenant_name)


def _override_db(tenant_name: str | None):
    async def _get_db():
        yield _FakeSession(tenant_name)

    return _get_db


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_manager_response_has_null_tenant_fields() -> None:
    app.dependency_overrides[get_current_user] = _manager
    app.dependency_overrides[get_db] = _override_db(None)

    response = client.get("/auth/me")

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "tenant_manager"
    assert body["tenant_id"] is None
    assert body["tenant_name"] is None


def test_admin_response_has_tenant_id_and_name() -> None:
    app.dependency_overrides[get_current_user] = _admin
    app.dependency_overrides[get_db] = _override_db(_TENANT_NAME)

    response = client.get("/auth/me")

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "tenant_admin"
    assert body["tenant_id"] == str(_TENANT_ID)
    assert body["tenant_name"] == _TENANT_NAME


def test_admin_tenant_name_matches_tenants_table() -> None:
    joined_name = "Beta Industries LLC"
    app.dependency_overrides[get_current_user] = _admin
    app.dependency_overrides[get_db] = _override_db(joined_name)

    response = client.get("/auth/me")

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_name"] == joined_name
    assert body["tenant_id"] == str(_TENANT_ID)
