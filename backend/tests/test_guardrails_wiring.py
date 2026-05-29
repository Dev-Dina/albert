"""Regression tests for guardrails chat wiring (Phase 6.1).

Historical bug: the chat routes POSTed to ``/input`` and ``/output``, which the
guardrails sidecar does not serve (it serves ``/check-input`` and
``/check-output``). Guardrails fails closed, so every chat returned 400.

These tests pin the wiring: both chat routes must call a *real* guardrails route
(via ``inference_client``), send the service-auth header, and preserve
fail-closed behavior. The previous suite patched ``_guardrails_check`` directly,
so it never exercised the outbound URL — these tests use a MockTransport that
captures the actual request path.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.api.routes import chat as chat_route
from app.api.routes import widget_chat as widget_chat_route

# Routes the guardrails sidecar actually serves (guardrails/app/main.py).
_VALID_GUARDRAILS_PATHS = {
    "/check-input",
    "/guardrails/input",
    "/check-output",
    "/guardrails/output",
}
# The buggy legacy paths that failed closed on every request.
_LEGACY_BAD_PATHS = {"/input", "/output"}

_CHAT_MODULES = [chat_route, widget_chat_route]


def _capture_transport(captured: list[tuple[str, str | None]], *, status_code: int = 200, body: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append((request.url.path, request.headers.get("Authorization")))
        return httpx.Response(status_code, json=body if body is not None else {"allowed": True})

    return httpx.MockTransport(handler)


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


@pytest.mark.parametrize("module", _CHAT_MODULES)
@pytest.mark.parametrize("endpoint,expected_path", [("input", "/check-input"), ("output", "/check-output")])
def test_guardrails_check_hits_real_route(monkeypatch, module, endpoint, expected_path) -> None:
    captured: list[tuple[str, str | None]] = []
    _patch_httpx(monkeypatch, _capture_transport(captured))

    allowed = asyncio.run(module._guardrails_check(endpoint, "hello"))

    assert allowed is True
    assert len(captured) == 1
    path, authorization = captured[0]
    assert path == expected_path
    assert path in _VALID_GUARDRAILS_PATHS
    assert path not in _LEGACY_BAD_PATHS
    # Service-to-service auth header is preserved.
    assert authorization is not None and authorization.startswith("Bearer ")


@pytest.mark.parametrize("module", _CHAT_MODULES)
def test_guardrails_check_fails_closed_on_non_200(monkeypatch, module) -> None:
    captured: list[tuple[str, str | None]] = []
    _patch_httpx(monkeypatch, _capture_transport(captured, status_code=404))
    assert asyncio.run(module._guardrails_check("input", "hi")) is False


@pytest.mark.parametrize("module", _CHAT_MODULES)
def test_guardrails_check_fails_closed_on_block(monkeypatch, module) -> None:
    captured: list[tuple[str, str | None]] = []
    _patch_httpx(monkeypatch, _capture_transport(captured, body={"allowed": False}))
    assert asyncio.run(module._guardrails_check("input", "hi")) is False


@pytest.mark.parametrize("module", _CHAT_MODULES)
def test_guardrails_check_fails_closed_on_transport_error(monkeypatch, module) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _patch_httpx(monkeypatch, httpx.MockTransport(handler))
    assert asyncio.run(module._guardrails_check("output", "hi")) is False
