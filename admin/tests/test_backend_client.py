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
