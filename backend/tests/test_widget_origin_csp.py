"""Origin + CSP hardening tests for US2.

Covers:
- T045: token exchange from a disallowed origin → 403 with an opaque body.
- T046: per-tenant `Content-Security-Policy: frame-ancestors …` on /widget/embed.html.
- T059b: origin removed from the allowlist → an existing-but-unexpired token is
  rejected (401) on the next chat call (SC-008 / "token replay after origin change").
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.security import mint_widget_session_token
from app.main import app

client = TestClient(app)


_TENANT_ID = uuid.uuid4()
_WIDGET_ID = uuid.uuid4()
_PUBLIC_WIDGET_ID = "Acm" + "C" * 19
_ALLOWED_ORIGIN_A = "https://demo.example.com"
_ALLOWED_ORIGIN_B = "https://docs.example.com"
_ATTACKER_ORIGIN = "https://attacker.test"
_KEY_MATERIAL = b"dev-tenant-signing-key-bytes-32!"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DIST = _REPO_ROOT / "widget" / "dist"
_BUNDLE_SHA = "0123456789"
_FILES_TO_STUB = (
    "widget.js",
    f"bundle-{_BUNDLE_SHA}.js",
    f"bundle-{_BUNDLE_SHA}.css",
    "bundle-manifest.json",
)


def setup_module(_) -> None:
    _DIST.mkdir(parents=True, exist_ok=True)
    for name in _FILES_TO_STUB:
        src = _DIST / name
        if src.exists():
            shutil.move(str(src), str(src) + ".bak")
    (_DIST / "widget.js").write_text("// stub", encoding="utf-8")
    (_DIST / f"bundle-{_BUNDLE_SHA}.js").write_text("// stub", encoding="utf-8")
    (_DIST / f"bundle-{_BUNDLE_SHA}.css").write_text("/* stub */", encoding="utf-8")
    (_DIST / "bundle-manifest.json").write_text(
        json.dumps(
            {
                "sha": _BUNDLE_SHA,
                "filename": f"bundle-{_BUNDLE_SHA}.js",
                "css": f"bundle-{_BUNDLE_SHA}.css",
            }
        ),
        encoding="utf-8",
    )


def teardown_module(_) -> None:
    for name in _FILES_TO_STUB:
        try:
            (_DIST / name).unlink()
        except FileNotFoundError:
            pass
        backup = _DIST / (name + ".bak")
        if backup.exists():
            shutil.move(str(backup), str(_DIST / name))


def _setup_session_dependencies(allowed: list[str]) -> None:
    from app.clients import vault_client
    from app.db.session import get_db
    from app.repositories import allowed_origin_repo, widget_repo
    from app.services import widget_session_service

    class _FakeSession:
        async def execute(self, *args, **kwargs):  # pragma: no cover - unused
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
        return tenant_id == _TENANT_ID and origin in allowed

    async def _fake_list_by_tenant(session, tenant_id):
        from app.db.models.widget_allowed_origin import WidgetAllowedOrigin

        return [
            WidgetAllowedOrigin(tenant_id=tenant_id, origin=o) for o in allowed
        ]

    async def _fake_read_key(tenant_id):
        return _KEY_MATERIAL if tenant_id == _TENANT_ID else None

    class _ActiveKey:
        version = 1

    async def _fake_active_key(session, tenant_id):
        return _ActiveKey() if tenant_id == _TENANT_ID else None

    app.dependency_overrides[get_db] = _fake_get_db
    widget_repo.get_by_public_id = _fake_get_by_public_id  # type: ignore[assignment]
    allowed_origin_repo.exists_for_tenant = _fake_exists_for_tenant  # type: ignore[assignment]
    allowed_origin_repo.list_by_tenant = _fake_list_by_tenant  # type: ignore[assignment]
    vault_client.read_tenant_widget_signing_key = _fake_read_key  # type: ignore[assignment]
    widget_session_service._fetch_active_key_version = _fake_active_key  # type: ignore[assignment]


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_token_exchange_from_attacker_origin_returns_403_opaque_body() -> None:
    """T045: attacker origin → 403; body identical to widget-not-found / disabled."""
    _setup_session_dependencies([_ALLOWED_ORIGIN_A])
    response = client.post(
        "/api/v1/widget/session",
        headers={"Origin": _ATTACKER_ORIGIN},
        json={"widget_id": _PUBLIC_WIDGET_ID},
    )
    assert response.status_code == 403
    body = response.json()
    # Opaque body: a single uniform "detail" string, no leak of which check failed.
    assert "detail" in body
    assert body["detail"] == "forbidden"
    for needle in ("origin", "allowlist", "disabled", "not found", "widget"):
        assert needle.lower() not in str(body).lower(), body


def test_token_exchange_for_unknown_widget_returns_same_opaque_403() -> None:
    """T045 (companion): the 403 body for a missing widget matches the bad-origin body."""
    _setup_session_dependencies([_ALLOWED_ORIGIN_A])
    response = client.post(
        "/api/v1/widget/session",
        headers={"Origin": _ALLOWED_ORIGIN_A},
        json={"widget_id": "Zzz" + "0" * 19},  # not the seeded id
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "forbidden"}


def test_embed_html_emits_per_tenant_frame_ancestors() -> None:
    """T046: per-tenant CSP frame-ancestors derived from the tenant's allowlist."""
    _setup_session_dependencies([_ALLOWED_ORIGIN_A, _ALLOWED_ORIGIN_B])
    response = client.get(
        "/widget/embed.html", params={"widget_id": _PUBLIC_WIDGET_ID}
    )
    assert response.status_code == 200, response.text
    csp = response.headers.get("content-security-policy", "")
    assert "frame-ancestors" in csp
    assert _ALLOWED_ORIGIN_A in csp
    assert _ALLOWED_ORIGIN_B in csp
    # Legacy X-Frame-Options for older browsers.
    assert response.headers.get("x-frame-options")


def test_chat_rejects_token_after_origin_removed_from_allowlist() -> None:
    """T059b / SC-008: an unexpired token from a now-removed origin is 401."""
    from app.api import deps
    from app.clients import vault_client
    from app.db.session import get_db
    from app.repositories import allowed_origin_repo

    token = mint_widget_session_token(
        tenant_id=_TENANT_ID,
        widget_id=_WIDGET_ID,
        public_widget_id=_PUBLIC_WIDGET_ID,
        origin=_ALLOWED_ORIGIN_A,
        key_version=1,
        key_material=_KEY_MATERIAL,
    )

    class _FakeSession:
        async def execute(self, *args, **kwargs):
            class _R:
                def scalar_one_or_none(self_inner):
                    class _Active:
                        version = 1
                    return _Active()
            return _R()

    async def _fake_get_db():
        yield _FakeSession()

    async def _fake_read_key(tenant_id):
        return _KEY_MATERIAL

    async def _fake_exists_for_tenant(session, tenant_id, origin):
        # Origin has just been removed.
        return False

    app.dependency_overrides[get_db] = _fake_get_db
    vault_client.read_tenant_widget_signing_key = _fake_read_key  # type: ignore[assignment]
    allowed_origin_repo.exists_for_tenant = _fake_exists_for_tenant  # type: ignore[assignment]

    async def _fake_active_key(db, tenant_id):
        class _Active:
            version = 1
        return _Active()

    deps._fetch_active_key_version = _fake_active_key  # type: ignore[assignment]

    response = client.post(
        "/api/v1/widget/chat",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": _ALLOWED_ORIGIN_A,
        },
        json={"message": "hi"},
    )
    assert response.status_code == 401


def test_chat_succeeds_when_origin_still_on_allowlist() -> None:
    """T059b companion: same token + allowed origin → 200 (no regression)."""
    from app.api import deps
    from app.clients import vault_client
    from app.db.session import get_db
    from app.repositories import allowed_origin_repo

    token = mint_widget_session_token(
        tenant_id=_TENANT_ID,
        widget_id=_WIDGET_ID,
        public_widget_id=_PUBLIC_WIDGET_ID,
        origin=_ALLOWED_ORIGIN_A,
        key_version=1,
        key_material=_KEY_MATERIAL,
    )

    class _FakeSession:
        async def execute(self, *args, **kwargs):
            class _R:
                def scalar_one_or_none(self_inner):
                    return None
            return _R()

    async def _fake_get_db():
        yield _FakeSession()

    async def _fake_read_key(tenant_id):
        return _KEY_MATERIAL

    async def _fake_exists_for_tenant(session, tenant_id, origin):
        return origin == _ALLOWED_ORIGIN_A

    async def _fake_active_key(db, tenant_id):
        class _Active:
            version = 1
        return _Active()

    app.dependency_overrides[get_db] = _fake_get_db
    vault_client.read_tenant_widget_signing_key = _fake_read_key  # type: ignore[assignment]
    allowed_origin_repo.exists_for_tenant = _fake_exists_for_tenant  # type: ignore[assignment]
    deps._fetch_active_key_version = _fake_active_key  # type: ignore[assignment]

    response = client.post(
        "/api/v1/widget/chat",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": _ALLOWED_ORIGIN_A,
        },
        json={"message": "hi"},
    )
    assert response.status_code == 200, response.text
