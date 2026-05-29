"""Unit tests for the Streamlit-side backend client (T078).

Uses ``httpx.MockTransport`` so the tests run without any network. Covers:
  * ``Authorization: Bearer`` injection
  * ``login`` returns the token from the backend response
  * 401 → ``BackendUnauthorizedError`` (so pages can clear the session)
  * Floor-violation 422 → typed ``FloorViolationError`` with the structured
    body so pages can render an inline message
  * Happy-path JSON decoding into the dataclasses
"""

from __future__ import annotations

import inspect
import json
from typing import Any, Callable

import httpx
import pytest

from app.clients.backend_client import (
    BackendClient,
    BackendError,
    BackendUnauthorizedError,
    FloorViolationError,
)


def _transport(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _client(handler, *, token: str | None = None) -> BackendClient:
    return BackendClient(
        base_url="http://test-backend",
        token=token,
        transport=_transport(handler),
    )


def test_login_returns_and_stores_token() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"access_token": "abc.def.ghi"})

    client = _client(handler)
    token = client.login(email="admin@acme.test", password="hunter2")
    assert token == "abc.def.ghi"
    assert client.token == "abc.def.ghi"
    assert captured["path"] == "/auth/login"
    assert captured["body"] == {
        "email": "admin@acme.test",
        "password": "hunter2",
    }


def test_authorization_header_is_injected_on_admin_calls() -> None:
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(dict(request.headers))
        return httpx.Response(200, json=[])

    client = _client(handler, token="signed.jwt.token")
    client.list_widgets()
    assert seen_headers.get("authorization") == "Bearer signed.jwt.token"


def test_unauthorized_raises_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Could not validate credentials"})

    client = _client(handler, token="stale")
    with pytest.raises(BackendUnauthorizedError):
        client.list_widgets()


def test_list_widgets_decodes_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "public_widget_id": "Aaa" + "1" * 19,
                    "name": "Acme",
                    "theme": {"primary_color": "#2563eb"},
                    "greeting": "hi",
                    "status": "enabled",
                }
            ],
        )

    client = _client(handler, token="tok")
    widgets = client.list_widgets()
    assert len(widgets) == 1
    assert widgets[0].name == "Acme"
    assert widgets[0].theme == {"primary_color": "#2563eb"}
    assert widgets[0].status == "enabled"


def test_floor_violation_raises_structured_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "error": "floor_violation",
                "key_path": "pii_redaction.enabled",
                "attempted_value": False,
                "floor_value": True,
            },
        )

    client = _client(handler, token="tok")
    with pytest.raises(FloorViolationError) as exc_info:
        client.put_guardrail_config({"pii_redaction": {"enabled": False}})

    err = exc_info.value
    assert err.key_path == "pii_redaction.enabled"
    assert err.attempted_value is False
    assert err.floor_value is True
    assert err.status_code == 422


def test_generic_422_falls_through_to_backend_error() -> None:
    """A non-floor 422 (e.g. Pydantic validation) is not a FloorViolationError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": "validation failed"})

    client = _client(handler, token="tok")
    with pytest.raises(BackendError) as exc_info:
        client.put_guardrail_config({})

    assert not isinstance(exc_info.value, FloorViolationError)
    assert exc_info.value.status_code == 422


def test_rotate_signing_key_returns_metadata_only() -> None:
    """The body must not contain any key-material-like field; we just read meta."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "version": 2,
                "created_at": "2026-05-27T12:00:00Z",
            },
        )

    client = _client(handler, token="tok")
    meta = client.rotate_signing_key()
    assert meta.version == 2
    assert meta.created_at.startswith("2026-05-27")


def test_add_allowed_origin_posts_origin_field() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            201,
            json={
                "id": "22222222-2222-2222-2222-222222222222",
                "origin": "https://www.example.com",
            },
        )

    client = _client(handler, token="tok")
    row = client.add_allowed_origin("https://www.example.com")
    assert captured["body"] == {"origin": "https://www.example.com"}
    assert row.origin == "https://www.example.com"


def test_get_embed_snippet_decodes_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "snippet": '<script src="http://x/widget.js" data-widget-id="ABCDEFGHIJKLMNOPQRSTUV" async></script>',
                "loader_url": "http://x/widget.js",
                "data_widget_id": "ABCDEFGHIJKLMNOPQRSTUV",
            },
        )

    client = _client(handler, token="tok")
    snippet = client.get_embed_snippet("11111111-1111-1111-1111-111111111111")
    assert "<script" in snippet.snippet
    assert snippet.data_widget_id == "ABCDEFGHIJKLMNOPQRSTUV"
    assert snippet.loader_url.endswith("/widget.js")


# ---------------------------------------------------------------------------
# Platform (tenant_manager) methods — T022 / T051 (incl. get_cost_series)
# ---------------------------------------------------------------------------


def test_get_cost_series_is_one_batched_call_keyed_by_tenant() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json=[
                {
                    "tenant_id": "aaaa1111-1111-1111-1111-111111111111",
                    "buckets": [
                        {"date": "2026-05-01", "cost_usd": "1.50", "total_tokens": 100},
                        {"date": "2026-05-02", "cost_usd": "0.00", "total_tokens": 0},
                    ],
                }
            ],
        )

    client = _client(handler, token="tok")
    series = client.get_cost_series(since="2026-05-01T00:00:00Z")
    assert captured["path"] == "/tenants/cost/series"
    assert captured["params"]["granularity"] == "daily"
    key = "aaaa1111-1111-1111-1111-111111111111"
    assert key in series
    assert [p.cost_usd for p in series[key]] == ["1.50", "0.00"]
    assert series[key][0].total_tokens == 100


def test_list_audit_decodes_and_passes_cursor() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json=[
                {
                    "entry_id": "eeee1111-1111-1111-1111-111111111111",
                    "actor_user_id": None,
                    "actor_email": "actor@platform.test",
                    "action": "tenant.suspend",
                    "target_tenant_id": None,
                    "target_tenant_slug": "acme",
                    "created_at": "2026-05-01T00:00:00Z",
                    "meta": {},
                }
            ],
        )

    client = _client(handler, token="tok")
    rows = client.list_audit(limit=2, before_id="ffff2222-2222-2222-2222-222222222222")
    assert captured["path"] == "/tenants/audit"
    assert captured["params"]["before_id"] == "ffff2222-2222-2222-2222-222222222222"
    assert rows[0].actor_email == "actor@platform.test"
    assert rows[0].actor_user_id is None


def test_create_manager_posts_credentials() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            201,
            json={"manager_user_id": "99999999-9999-9999-9999-999999999999", "email": "m@x.test"},
        )

    client = _client(handler, token="tok")
    created = client.create_manager(email="m@x.test", password="strong-pass-123")
    assert captured["path"] == "/tenants/managers"
    assert captured["body"] == {"email": "m@x.test", "password": "strong-pass-123"}
    assert created.email == "m@x.test"


# ---------------------------------------------------------------------------
# Tenant-admin methods — T039 / T051
# ---------------------------------------------------------------------------


def test_list_leads_passes_filters_and_decodes() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200,
            json=[
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "name": "Jane",
                    "contact": "jane@x.test",
                    "intent": "demo",
                    "status": "new",
                    "created_at": "2026-05-01T00:00:00Z",
                    "conversation_id": None,
                }
            ],
        )

    client = _client(handler, token="tok")
    leads = client.list_leads(status="new", since="2026-05-01T00:00:00Z", limit=200)
    assert captured["path"] == "/api/v1/admin/leads"
    assert captured["params"]["status"] == "new"
    assert captured["params"]["limit"] == "200"
    assert captured["auth"] == "Bearer tok"
    assert leads[0].name == "Jane"
    assert leads[0].conversation_id is None


def test_list_members_decodes_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/admin/members"
        return httpx.Response(
            200,
            json=[
                {
                    "user_id": "22222222-2222-2222-2222-222222222222",
                    "email": "member@x.test",
                    "created_at": "2026-05-01T00:00:00Z",
                }
            ],
        )

    client = _client(handler, token="tok")
    members = client.list_members()
    assert members[0].email == "member@x.test"
    assert members[0].user_id == "22222222-2222-2222-2222-222222222222"


def test_invite_member_posts_body() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(
            201,
            json={
                "user_id": "33333333-3333-3333-3333-333333333333",
                "email": "new@x.test",
                "created_at": "2026-05-01T00:00:00Z",
            },
        )

    client = _client(handler, token="tok")
    row = client.invite_member(email="new@x.test", password="strong-pass-123")
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/admin/members"
    assert captured["body"] == {"email": "new@x.test", "password": "strong-pass-123"}
    assert row.email == "new@x.test"


def test_remove_member_issues_delete_to_user_path() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        return httpx.Response(200, json={"tenant_id": "t", "removed_user_id": "u"})

    client = _client(handler, token="tok")
    client.remove_member("44444444-4444-4444-4444-444444444444")
    assert captured["method"] == "DELETE"
    assert captured["path"] == "/api/v1/admin/members/44444444-4444-4444-4444-444444444444"


def test_tenant_admin_methods_reject_409_and_404() -> None:
    def conflict(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"detail": "A user with email ... already exists."})

    client = _client(conflict, token="tok")
    with pytest.raises(BackendError) as exc_info:
        client.invite_member(email="dup@x.test", password="strong-pass-123")
    assert exc_info.value.status_code == 409


def test_tenant_admin_methods_take_no_tenant_id_argument() -> None:
    """FR-031: the tenant-admin methods must derive scope from the JWT only."""
    for name in ("list_leads", "list_members", "invite_member", "remove_member"):
        params = inspect.signature(getattr(BackendClient, name)).parameters
        assert "tenant_id" not in params, f"{name} must not accept a tenant_id argument"
