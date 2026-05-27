"""Contract tests for POST /api/v1/widget/session (US1 happy path).

These tests stub the DB and Vault dependencies so the route logic — schema
validation, dependency wiring, response shape — is exercised in isolation.
Real DB integration runs in test_widget_e2e_chat.py.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


_TENANT_ID = uuid.uuid4()
_WIDGET_ID = uuid.uuid4()
_PUBLIC_WIDGET_ID = "Acm" + "X" * 19  # 22 base62 chars
_ORIGIN = "http://localhost:8080"
_KEY_MATERIAL = b"dev-tenant-signing-key-bytes-32!"


def _setup_widget_dependencies() -> None:
    """Override DB + Vault deps so the session route runs against in-memory state."""
    from app import repositories  # noqa: F401
    from app.clients import vault_client
    from app.db.session import get_db
    from app.repositories import allowed_origin_repo, widget_repo

    class _FakeSession:
        async def execute(self, *args, **kwargs):  # pragma: no cover - not used
            class _R:
                def scalar_one_or_none(self_inner):
                    return None
            return _R()

    async def _fake_get_db():
        yield _FakeSession()

    async def _fake_get_by_public_id(session, public_widget_id):
        if public_widget_id != _PUBLIC_WIDGET_ID:
            return None
        return widget_repo.PublicWidgetLookup(
            widget_id=_WIDGET_ID, tenant_id=_TENANT_ID, status="enabled"
        )

    async def _fake_exists_for_tenant(session, tenant_id, origin):
        return tenant_id == _TENANT_ID and origin == _ORIGIN

    async def _fake_read_key(tenant_id):
        return _KEY_MATERIAL if tenant_id == _TENANT_ID else None

    # active key version row
    class _ActiveKey:
        version = 1

    async def _fake_active_key(session, tenant_id):
        return _ActiveKey() if tenant_id == _TENANT_ID else None

    app.dependency_overrides[get_db] = _fake_get_db
    widget_repo.get_by_public_id = _fake_get_by_public_id  # type: ignore[assignment]
    allowed_origin_repo.exists_for_tenant = _fake_exists_for_tenant  # type: ignore[assignment]
    vault_client.read_tenant_widget_signing_key = _fake_read_key  # type: ignore[assignment]
    # active key lookup used by widget_session_service
    from app.services import widget_session_service
    widget_session_service._fetch_active_key_version = _fake_active_key  # type: ignore[assignment]


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_session_success_returns_token_and_ttl() -> None:
    _setup_widget_dependencies()
    response = client.post(
        "/api/v1/widget/session",
        headers={"Origin": _ORIGIN},
        json={"widget_id": _PUBLIC_WIDGET_ID},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "session_token" in body
    assert body["session_token"]
    assert body["ttl_seconds"] == 900
    assert body["expires_in"] == 900


def test_session_token_carries_expected_claims() -> None:
    from jose import jwt as jose_jwt
    _setup_widget_dependencies()
    response = client.post(
        "/api/v1/widget/session",
        headers={"Origin": _ORIGIN},
        json={"widget_id": _PUBLIC_WIDGET_ID},
    )
    assert response.status_code == 200
    token = response.json()["session_token"]
    claims = jose_jwt.decode(token, _KEY_MATERIAL, algorithms=["HS256"])
    assert claims["tnt"] == str(_TENANT_ID)
    assert claims["wid"] == str(_WIDGET_ID)
    assert claims["kvr"] == 1
    assert claims["org"] == _ORIGIN
    assert claims["sub"] == f"widget:{_PUBLIC_WIDGET_ID}"


def test_session_body_with_tenant_id_field_is_rejected() -> None:
    """FR-009 at the schema layer: extra fields rejected with 422."""
    _setup_widget_dependencies()
    response = client.post(
        "/api/v1/widget/session",
        headers={"Origin": _ORIGIN},
        json={
            "widget_id": _PUBLIC_WIDGET_ID,
            "tenant_id": str(uuid.uuid4()),  # attempt to inject foreign tenant
        },
    )
    assert response.status_code == 422


def test_session_malformed_widget_id_returns_422() -> None:
    _setup_widget_dependencies()
    response = client.post(
        "/api/v1/widget/session",
        headers={"Origin": _ORIGIN},
        json={"widget_id": "not-a-valid-id"},
    )
    assert response.status_code == 422
