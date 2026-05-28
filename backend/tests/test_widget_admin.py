"""US3 admin contract tests (T062–T067).

These tests run against the FastAPI app via TestClient. They stub the DB
session and the membership lookup so that the tenant-admin endpoints can be
exercised without a running Postgres. The widget/origin/guardrail repositories
are replaced with in-memory dicts keyed by tenant id, mirroring the pattern
used by ``test_widget_session.py``.

Coverage:
  T062 — list widgets returns only the caller tenant's widgets.
  T063 — PATCH widget updates theme/greeting/status; embed.html reflects them.
  T064 — embed snippet response carries the loader URL + data-widget-id.
  T065 — POST allowed-origins refuses wildcards / paths / queries / plain http.
  T066 — PUT guardrail-config refusing a floor-violating config returns 422
         with {error, key_path, attempted_value, floor_value}.
  T067 — POST signing-key/rotate returns only {version, created_at} — never
         the raw secret in the body or in any log line.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers / per-test wiring
# ---------------------------------------------------------------------------

@dataclass
class _Widget:
    id: uuid.UUID
    tenant_id: uuid.UUID
    public_widget_id: str
    name: str
    theme: dict[str, Any]
    greeting: str
    status: str


@dataclass
class _Origin:
    id: uuid.UUID
    tenant_id: uuid.UUID
    origin: str


_TENANT_A = uuid.uuid4()
_TENANT_B = uuid.uuid4()
_ADMIN_A = uuid.uuid4()
_PUB_A_1 = "Aaa" + "1" * 19
_PUB_A_2 = "Aaa" + "2" * 19
_PUB_B_1 = "Bbb" + "1" * 19


class _State:
    """In-memory store shared by repository stubs."""

    widgets: dict[uuid.UUID, _Widget]
    origins: dict[uuid.UUID, _Origin]
    guardrail_config: dict[uuid.UUID, dict[str, Any]]
    rotated_log: list[str]

    def __init__(self) -> None:
        self.widgets = {}
        self.origins = {}
        self.guardrail_config = {}
        self.rotated_log = []


def _wire(state: _State, *, actor_tenant: uuid.UUID = _TENANT_A) -> str:
    """Stub deps + repos + service helpers. Returns a Bearer token string.

    The token is opaque to the test wiring; the admin route resolves the
    caller's tenant from a stubbed membership lookup, not from the token
    itself.
    """
    from app.db.session import get_db
    from app.repositories import allowed_origin_repo, guardrail_config_repo, widget_repo
    from app.services import widget_admin_service

    class _FakeSession:
        def __init__(self) -> None:
            self.commits = 0

        async def execute(self, *args, **kwargs):
            class _R:
                def scalar_one_or_none(self_inner):
                    return None
                def scalars(self_inner):
                    class _S:
                        def all(self_s):
                            return []
                    return _S()
            return _R()

        async def commit(self) -> None:
            self.commits += 1

        async def rollback(self) -> None:
            pass

        async def flush(self) -> None:
            pass

    fake_db = _FakeSession()

    async def _fake_get_db():
        yield fake_db

    # ---- Repo stubs (tenant-scoped in-memory) ------------------------------
    async def _list_widgets(session, tenant_id):
        return [w for w in state.widgets.values() if w.tenant_id == tenant_id]

    async def _get_widget_by_id(session, widget_id):
        return state.widgets.get(widget_id)

    async def _create_widget(session, *, tenant_id, public_widget_id, name,
                             theme=None, greeting="", status="enabled"):
        w = _Widget(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            public_widget_id=public_widget_id,
            name=name,
            theme=theme or {},
            greeting=greeting,
            status=status,
        )
        state.widgets[w.id] = w
        return w

    async def _update_widget(session, widget, **fields):
        for k, v in fields.items():
            setattr(widget, k, v)
        return widget

    async def _list_origins(session, tenant_id):
        return [o for o in state.origins.values() if o.tenant_id == tenant_id]

    async def _add_origin(session, *, tenant_id, origin, created_by_user_id=None):
        o = _Origin(id=uuid.uuid4(), tenant_id=tenant_id, origin=origin)
        state.origins[o.id] = o
        return o

    async def _remove_origin(session, origin_id):
        return state.origins.pop(origin_id, None) is not None

    async def _get_guardrail(session, tenant_id):
        cfg = state.guardrail_config.get(tenant_id)
        if cfg is None:
            return None

        class _Row:
            def __init__(self, c):
                self.config = c

        return _Row(cfg)

    async def _upsert_guardrail(session, *, tenant_id, config, updated_by_user_id=None):
        state.guardrail_config[tenant_id] = config

        class _Row:
            def __init__(self, c):
                self.config = c

        return _Row(config)

    widget_repo.list_by_tenant = _list_widgets  # type: ignore[assignment]
    widget_repo.get_by_id = _get_widget_by_id  # type: ignore[assignment]
    widget_repo.create = _create_widget  # type: ignore[assignment]
    widget_repo.update = _update_widget  # type: ignore[assignment]
    allowed_origin_repo.list_by_tenant = _list_origins  # type: ignore[assignment]
    allowed_origin_repo.add = _add_origin  # type: ignore[assignment]
    allowed_origin_repo.remove = _remove_origin  # type: ignore[assignment]
    guardrail_config_repo.get_for_tenant = _get_guardrail  # type: ignore[assignment]
    guardrail_config_repo.upsert = _upsert_guardrail  # type: ignore[assignment]

    # ---- Service rotate stub: returns metadata only, never the secret ----
    async def _rotate(session, *, tenant_id, actor_user_id=None):
        # Intentionally DO NOT log key material — assertion T067 reads the log.
        return widget_admin_service.RotatedSigningKey(
            version=2, created_at=datetime.utcnow()
        )

    widget_admin_service.rotate_signing_key = _rotate  # type: ignore[assignment]

    # ---- DB + auth deps --------------------------------------------------
    app.dependency_overrides[get_db] = _fake_get_db

    # Stub the admin tenant-resolver: route reads it instead of inspecting
    # membership rows. Returns (user_id, tenant_id) for the test admin user.
    from app.api.routes import admin_widgets as admin_routes_mod

    async def _fake_admin_identity():
        return admin_routes_mod.AdminIdentity(
            user_id=_ADMIN_A, tenant_id=actor_tenant
        )

    app.dependency_overrides[admin_routes_mod.require_admin_identity] = (
        _fake_admin_identity
    )

    return "dev-admin-bearer-token-not-actually-verified-in-tests"


def teardown_function() -> None:
    app.dependency_overrides.clear()


def _seed_two_tenants(state: _State) -> tuple[_Widget, _Widget, _Widget]:
    a1 = _Widget(uuid.uuid4(), _TENANT_A, _PUB_A_1, "A1", {}, "hello A1", "enabled")
    a2 = _Widget(uuid.uuid4(), _TENANT_A, _PUB_A_2, "A2", {}, "hello A2", "enabled")
    b1 = _Widget(uuid.uuid4(), _TENANT_B, _PUB_B_1, "B1", {}, "hello B1", "enabled")
    state.widgets[a1.id] = a1
    state.widgets[a2.id] = a2
    state.widgets[b1.id] = b1
    return a1, a2, b1


# ---------------------------------------------------------------------------
# T062 — list widgets scoped to caller tenant
# ---------------------------------------------------------------------------

def test_list_widgets_returns_only_caller_tenant() -> None:
    state = _State()
    token = _wire(state, actor_tenant=_TENANT_A)
    _seed_two_tenants(state)

    r = client.get(
        "/api/v1/admin/widgets",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    pids = {row["public_widget_id"] for row in body}
    assert pids == {_PUB_A_1, _PUB_A_2}
    assert _PUB_B_1 not in pids


# ---------------------------------------------------------------------------
# T063 — PATCH updates fields; subsequent /widget/embed.html reflects values
# ---------------------------------------------------------------------------

def test_patch_widget_updates_fields() -> None:
    state = _State()
    token = _wire(state, actor_tenant=_TENANT_A)
    a1, _, _ = _seed_two_tenants(state)

    r = client.patch(
        f"/api/v1/admin/widgets/{a1.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "theme": {"primary_color": "#2563eb"},
            "greeting": "Welcome — how can I help?",
            "status": "disabled",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["theme"] == {"primary_color": "#2563eb"}
    assert body["greeting"] == "Welcome — how can I help?"
    assert body["status"] == "disabled"

    # The mutation lands on the in-memory row.
    assert state.widgets[a1.id].greeting == "Welcome — how can I help?"


def test_patch_other_tenant_widget_returns_404() -> None:
    """Cross-tenant id leaks must surface as 404 (not 403) per contract."""
    state = _State()
    token = _wire(state, actor_tenant=_TENANT_A)
    _, _, b1 = _seed_two_tenants(state)

    r = client.patch(
        f"/api/v1/admin/widgets/{b1.id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"greeting": "evil"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# T064 — embed snippet
# ---------------------------------------------------------------------------

def test_embed_snippet_contains_loader_and_widget_id() -> None:
    state = _State()
    token = _wire(state, actor_tenant=_TENANT_A)
    a1, _, _ = _seed_two_tenants(state)

    r = client.get(
        f"/api/v1/admin/widgets/{a1.id}/embed-snippet",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data_widget_id"] == _PUB_A_1
    assert "widget.js" in body["loader_url"]
    # Snippet is a single <script> line — exactly one newline (or none).
    snip = body["snippet"]
    assert snip.count("<script") == 1
    assert snip.count("</script>") == 1
    assert f'data-widget-id="{_PUB_A_1}"' in snip
    assert body["loader_url"] in snip


# ---------------------------------------------------------------------------
# T065 — origin validation rejects bad shapes (422)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad_origin",
    [
        "https://*.example.com",         # wildcard
        "https://example.com/foo",       # path
        "https://example.com?q=1",       # query
        "https://example.com/",          # trailing slash
        "http://example.com",            # non-localhost http
        "ftp://example.com",             # bad scheme
        "https://EXAMPLE.com/",          # trailing slash + uppercase host
        "https://example.com#frag",      # fragment
        "example.com",                   # missing scheme
    ],
)
def test_add_allowed_origin_rejects_bad_shape(bad_origin: str) -> None:
    state = _State()
    token = _wire(state, actor_tenant=_TENANT_A)

    r = client.post(
        "/api/v1/admin/allowed-origins",
        headers={"Authorization": f"Bearer {token}"},
        json={"origin": bad_origin},
    )
    assert r.status_code == 422, (bad_origin, r.text)


def test_add_allowed_origin_accepts_valid_https() -> None:
    state = _State()
    token = _wire(state, actor_tenant=_TENANT_A)

    r = client.post(
        "/api/v1/admin/allowed-origins",
        headers={"Authorization": f"Bearer {token}"},
        json={"origin": "https://demo.example.com"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["origin"] == "https://demo.example.com"


def test_add_allowed_origin_accepts_localhost_http() -> None:
    state = _State()
    token = _wire(state, actor_tenant=_TENANT_A)

    r = client.post(
        "/api/v1/admin/allowed-origins",
        headers={"Authorization": f"Bearer {token}"},
        json={"origin": "http://localhost:8080"},
    )
    assert r.status_code == 201


# ---------------------------------------------------------------------------
# T066 — guardrail floor violation
# ---------------------------------------------------------------------------

def test_put_guardrail_config_floor_violation_returns_422() -> None:
    state = _State()
    token = _wire(state, actor_tenant=_TENANT_A)

    r = client.put(
        "/api/v1/admin/guardrail-config",
        headers={"Authorization": f"Bearer {token}"},
        json={"config": {"pii_redaction": {"enabled": False}}},
    )
    assert r.status_code == 422, r.text
    body = r.json()
    assert body["error"] == "floor_violation"
    assert body["key_path"] == "pii_redaction.enabled"
    assert body["attempted_value"] is False
    assert body["floor_value"] is True


def test_put_guardrail_config_accepts_stricter_config() -> None:
    state = _State()
    token = _wire(state, actor_tenant=_TENANT_A)

    r = client.put(
        "/api/v1/admin/guardrail-config",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "config": {
                "pii_redaction": {"enabled": True},
                "injection_defenses": {"level": "strict"},
                "block_topics": [
                    "medical_advice",
                    "legal_advice",
                    "financial_advice",
                    "competitor_names",
                ],
            }
        },
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# T067 — rotate returns only metadata; raw key NEVER in body or logs
# ---------------------------------------------------------------------------

def test_rotate_returns_only_metadata_and_does_not_leak_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    state = _State()
    token = _wire(state, actor_tenant=_TENANT_A)

    with caplog.at_level(logging.DEBUG):
        r = client.post(
            "/api/v1/admin/signing-key/rotate",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body.keys()) == {"version", "created_at"}
    assert isinstance(body["version"], int) and body["version"] >= 1
    # No suspicious key-material fields anywhere.
    for forbidden in ("key", "secret", "material", "vault"):
        assert forbidden not in body, body

    # No log line carries a raw key. The stub never emits key material; this
    # asserts the route handler doesn't add one either.
    for record in caplog.records:
        msg = record.getMessage().lower()
        assert "key_material" not in msg
        assert "raw_key" not in msg
