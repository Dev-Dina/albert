"""Loader and embed-page contract tests (US1 baseline; US2 adds CSP details).

These tests exercise the static routes; they create a tiny widget.js + an
embed manifest in widget/dist before running so the routes have something to
serve. Any pre-existing built bundle is backed up and restored on teardown
so a real `node esbuild.config.mjs` build (and the preview server that reads
the manifest) keeps working after pytest.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DIST = _REPO_ROOT / "widget" / "dist"
_LOADER_SRC = (
    "(()=>{const s=document.currentScript;if(!s)return;"
    "const id=s.getAttribute('data-widget-id');"
    "if(!id||!/^[A-Za-z0-9]{22}$/.test(id)){"
    "console.error('[albert-widget] data-widget-id is missing or invalid');return;}"
    "const f=document.createElement('iframe');"
    "f.src=new URL('/widget/embed.html?widget_id='+id,location.origin).toString();"
    "f.setAttribute('sandbox','allow-scripts allow-same-origin allow-forms');"
    "document.body.appendChild(f);})();"
)
_BUNDLE_SHA = "0123456789"
_BUNDLE_SRC = "/* widget bundle test stub */ export const ok=true;"
_BUNDLE_CSS = ".albert-chat{background:#fff}"

_FILES_TO_STUB = (
    "widget.js",
    f"bundle-{_BUNDLE_SHA}.js",
    f"bundle-{_BUNDLE_SHA}.css",
    "bundle-manifest.json",
)


def setup_module(_) -> None:
    _DIST.mkdir(parents=True, exist_ok=True)
    # Back up any pre-existing artifacts so the real build survives the run.
    for name in _FILES_TO_STUB:
        src = _DIST / name
        if src.exists():
            shutil.move(str(src), str(src) + ".bak")

    (_DIST / "widget.js").write_text(_LOADER_SRC, encoding="utf-8")
    (_DIST / f"bundle-{_BUNDLE_SHA}.js").write_text(_BUNDLE_SRC, encoding="utf-8")
    (_DIST / f"bundle-{_BUNDLE_SHA}.css").write_text(_BUNDLE_CSS, encoding="utf-8")
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
            os.remove(_DIST / name)
        except FileNotFoundError:
            pass
    # Restore any artifacts the build produced before the test ran.
    for name in _FILES_TO_STUB:
        backup = _DIST / (name + ".bak")
        if backup.exists():
            shutil.move(str(backup), str(_DIST / name))


def test_widget_js_served_with_correct_headers() -> None:
    response = client.get("/widget.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert response.headers["cache-control"] == "public, max-age=60"
    assert "data-widget-id" in response.text


def test_widget_js_loader_fails_closed_without_data_widget_id() -> None:
    """The loader body must contain the fail-closed branch (FR-005)."""
    response = client.get("/widget.js")
    assert "missing or invalid" in response.text


def _wire_embed_deps(*, widget_status: str = "enabled", origins: list[str] | None = None) -> None:
    import uuid as _uuid

    from app.clients import vault_client  # noqa: F401
    from app.db.session import get_db
    from app.repositories import allowed_origin_repo, widget_repo

    tenant_id = _uuid.uuid4()
    widget_id = _uuid.uuid4()

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
            widget_id=widget_id, tenant_id=tenant_id, status=widget_status
        )

    async def _fake_list_by_tenant(session, t_id):
        from app.db.models.widget_allowed_origin import WidgetAllowedOrigin

        return [WidgetAllowedOrigin(tenant_id=t_id, origin=o) for o in (origins or [])]

    app.dependency_overrides[get_db] = _fake_get_db
    widget_repo.get_by_public_id = _fake_get_by_public_id  # type: ignore[assignment]
    allowed_origin_repo.list_by_tenant = _fake_list_by_tenant  # type: ignore[assignment]


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_embed_html_includes_bundle_and_stylesheet() -> None:
    _wire_embed_deps(origins=["http://localhost:8080"])
    response = client.get(
        "/widget/embed.html", params={"widget_id": "Acm" + "Z" * 19}
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert f"/widget/bundle-{_BUNDLE_SHA}.js" in body
    assert f"/widget/bundle-{_BUNDLE_SHA}.css" in body
    assert "Content-Security-Policy" in response.headers


def test_embed_html_returns_404_for_disabled_widget() -> None:
    _wire_embed_deps(widget_status="disabled", origins=["http://localhost:8080"])
    response = client.get(
        "/widget/embed.html", params={"widget_id": "Acm" + "D" * 19}
    )
    assert response.status_code == 404


def test_embed_html_returns_404_when_tenant_has_no_origins() -> None:
    _wire_embed_deps(origins=[])
    response = client.get(
        "/widget/embed.html", params={"widget_id": "Acm" + "Z" * 19}
    )
    assert response.status_code == 404


def test_bundle_js_served_with_immutable_cache() -> None:
    response = client.get(f"/widget/bundle-{_BUNDLE_SHA}.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert "immutable" in response.headers["cache-control"]
    assert "max-age=31536000" in response.headers["cache-control"]


def test_bundle_css_served_with_immutable_cache() -> None:
    response = client.get(f"/widget/bundle-{_BUNDLE_SHA}.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert "immutable" in response.headers["cache-control"]
    assert "max-age=31536000" in response.headers["cache-control"]
    assert ".albert-chat" in response.text


def test_bundle_route_rejects_other_extensions() -> None:
    response = client.get("/widget/bundle-0123456789.html")
    assert response.status_code == 404


def test_bundle_route_rejects_path_traversal() -> None:
    response = client.get("/widget/..%2fetc%2fpasswd")
    assert response.status_code in (404, 400)
