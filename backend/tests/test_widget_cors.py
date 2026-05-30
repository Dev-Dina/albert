"""Widget CORS posture under Approach A (feature 006).

The per-tenant ``WidgetCorsMiddleware`` has been REMOVED: the backend no longer
emits ``Access-Control-Allow-Origin`` for the widget endpoints. Cross-origin
in-browser reads are therefore blocked by the browser same-origin policy;
embedding is bounded by the per-tenant ``frame-ancestors`` CSP on
``embed.html``, and tenant identity by the signed session token. These tests
lock in that NO ACAO header is emitted on the widget surface (so a non-embedded
cross-origin caller can never read a widget response in a browser).
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


_TENANT_ID = uuid.uuid4()
_WIDGET_ID = uuid.uuid4()
_PUBLIC_WIDGET_ID = "Acm" + "O" * 19
_ORIGIN = "https://demo.example.com"
_KEY_MATERIAL = b"dev-tenant-signing-key-bytes-32!"


def _wire_widget() -> None:
    """Stub DB + Vault so /session returns 200 for an enabled widget."""
    from app.clients import vault_client
    from app.db.session import get_db
    from app.repositories import widget_repo
    from app.services import widget_session_service

    class _FakeSession:
        async def execute(self, *args, **kwargs):
            _sql = str(args[0]).lower() if args else ""
            _active = "tenants.status" in _sql or "from tenants" in _sql
            class _R:
                def scalar_one_or_none(self_inner):
                    return "active" if _active else None
            return _R()

    async def _fake_get_db():
        yield _FakeSession()

    async def _fake_get_by_public_id(session, public_widget_id):
        return widget_repo.PublicWidgetLookup(
            widget_id=_WIDGET_ID, tenant_id=_TENANT_ID, status="enabled"
        )

    async def _fake_read_key(tenant_id):
        return _KEY_MATERIAL

    class _ActiveKey:
        version = 1

    async def _fake_active_key(session, tenant_id):
        return _ActiveKey()

    app.dependency_overrides[get_db] = _fake_get_db
    widget_repo.get_by_public_id = _fake_get_by_public_id  # type: ignore[assignment]
    vault_client.read_tenant_widget_signing_key = _fake_read_key  # type: ignore[assignment]
    widget_session_service._fetch_active_key_version = _fake_active_key  # type: ignore[assignment]


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_session_response_carries_no_acao_header() -> None:
    """A successful /session response emits no Access-Control-Allow-Origin: with
    the middleware gone, the browser same-origin policy blocks any cross-origin
    caller from reading the body."""
    _wire_widget()
    response = client.post(
        "/api/v1/widget/session",
        headers={"Origin": _ORIGIN},
        json={"widget_id": _PUBLIC_WIDGET_ID},
    )
    assert response.status_code == 200, response.text
    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}


def test_chat_preflight_is_not_granted_acao() -> None:
    """No widget CORS handler remains, so an OPTIONS preflight to /chat is never
    answered with an ACAO echoing the caller's origin."""
    response = client.options(
        "/api/v1/widget/chat",
        headers={
            "Origin": _ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.headers.get("access-control-allow-origin") is None
