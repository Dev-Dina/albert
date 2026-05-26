import asyncio
import logging

import httpx
import pytest

from app.clients import inference_client
from app.core.config import settings


def _expected_bearer() -> str:
    return f"Bearer {settings.service_auth_token.get_secret_value()}"


def _patch_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Force AsyncClients created in inference_client to use a MockTransport."""
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def _factory(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


def test_service_auth_headers() -> None:
    assert inference_client.service_auth_headers() == {
        "Authorization": _expected_bearer()
    }


def test_call_attaches_header(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"label": "unknown", "confidence": 0.0})

    _patch_transport(monkeypatch, handler)

    response = asyncio.run(inference_client.call_modelserver_predict({"text": "hi"}))

    assert response.status_code == 200
    assert captured["auth"] == _expected_bearer()


def test_token_not_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"allowed": True})

    _patch_transport(monkeypatch, handler)

    with caplog.at_level(logging.DEBUG):
        asyncio.run(inference_client.call_guardrails_check_input({"text": "x"}))

    token = settings.service_auth_token.get_secret_value()
    assert token not in caplog.text
