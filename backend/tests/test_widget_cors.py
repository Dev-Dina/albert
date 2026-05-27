"""Per-tenant CORS middleware contract test (T055b, FR-012, FR-015).

For a tenant with allowlist [origin_a]:
- A POST to /api/v1/widget/session with Origin: origin_a returns
  Access-Control-Allow-Origin: origin_a AND Vary: Origin.
- The same call with Origin: attacker.test returns 403 with NO ACAO header.
- An OPTIONS preflight to /api/v1/widget/chat echoes only allowed origins.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


_TENANT_ID = uuid.uuid4()
_WIDGET_ID = uuid.uuid4()
_PUBLIC_WIDGET_ID = "Acm" + "O" * 19
_ALLOWED = "https://demo.example.com"
_ATTACKER = "https://attacker.test"
_KEY_MATERIAL = b"dev-tenant-signing-key-bytes-32!"


def _wire_for_allowlist(allowed: list[str]) -> None:
    from app.clients import vault_client
    from app.db.session import get_db
    from app.repositories import allowed_origin_repo, widget_repo
    from app.services import widget_session_service

    class _FakeSession:
        async def execute(self, *args, **kwargs):
            class _R:
                def scalar_one_or_none(self_inner):
                    return None
            return _R()

    async def _fake_get_db():
        yield _FakeSession()

    async def _fake_get_by_public_id(session, public_widget_id):
        return widget_repo.PublicWidgetLookup(
            widget_id=_WIDGET_ID, tenant_id=_TENANT_ID, status="enabled"
        )

    async def _fake_exists_for_tenant(session, tenant_id, origin):
        return origin in allowed

    async def _fake_read_key(tenant_id):
        return _KEY_MATERIAL

    class _ActiveKey:
        version = 1

    async def _fake_active_key(session, tenant_id):
        return _ActiveKey()

    app.dependency_overrides[get_db] = _fake_get_db
    widget_repo.get_by_public_id = _fake_get_by_public_id  # type: ignore[assignment]
    allowed_origin_repo.exists_for_tenant = _fake_exists_for_tenant  # type: ignore[assignment]
    vault_client.read_tenant_widget_signing_key = _fake_read_key  # type: ignore[assignment]
    widget_session_service._fetch_active_key_version = _fake_active_key  # type: ignore[assignment]


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_cors_allowed_origin_sets_acao_and_vary() -> None:
    _wire_for_allowlist([_ALLOWED])
    response = client.post(
        "/api/v1/widget/session",
        headers={"Origin": _ALLOWED},
        json={"widget_id": _PUBLIC_WIDGET_ID},
    )
    assert response.status_code == 200, response.text
    assert response.headers.get("access-control-allow-origin") == _ALLOWED
    vary = response.headers.get("vary", "")
    assert "Origin" in vary


def test_cors_disallowed_origin_omits_acao_and_returns_403() -> None:
    _wire_for_allowlist([_ALLOWED])
    response = client.post(
        "/api/v1/widget/session",
        headers={"Origin": _ATTACKER},
        json={"widget_id": _PUBLIC_WIDGET_ID},
    )
    # 403 from the server-side origin check (CORS is defense-in-depth, not the
    # trust boundary). NO Access-Control-Allow-Origin header.
    assert response.status_code == 403
    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}


def test_cors_preflight_echoes_only_allowed_origin() -> None:
    _wire_for_allowlist([_ALLOWED])
    # Preflight requires resolving tenant from token, but tokenless preflight
    # has no tenant context; the middleware MUST still refuse to echo an
    # attacker origin. We accept either 200/204 with ACAO==allowed for the
    # allowed-origin case, or 403/no-ACAO for the attacker case.
    allowed_pre = client.options(
        "/api/v1/widget/chat",
        headers={
            "Origin": _ALLOWED,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    attacker_pre = client.options(
        "/api/v1/widget/chat",
        headers={
            "Origin": _ATTACKER,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    # Attacker preflight must NEVER receive an ACAO header echoing its origin.
    acao = attacker_pre.headers.get("access-control-allow-origin")
    assert acao != _ATTACKER
    # Allowed preflight: if we respond at all, we must echo only the allowed origin.
    allowed_acao = allowed_pre.headers.get("access-control-allow-origin")
    if allowed_acao is not None:
        assert allowed_acao == _ALLOWED
