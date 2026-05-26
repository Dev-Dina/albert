import asyncio

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.core.request_context as request_context
from app.clients import inference_client
from app.core.config import settings
from app.core.request_context import (
    REQUEST_ID_HEADER,
    RequestIdMiddleware,
    get_request_id,
)


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"request_id": get_request_id() or ""}

    return app


def test_generates_request_id_when_missing() -> None:
    client = TestClient(_app())
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.headers.get(REQUEST_ID_HEADER)


def test_reuses_inbound_request_id() -> None:
    client = TestClient(_app())
    response = client.get("/ping", headers={REQUEST_ID_HEADER: "inbound-123"})
    assert response.headers.get(REQUEST_ID_HEADER) == "inbound-123"


def test_rejects_unsafe_inbound_request_id() -> None:
    client = TestClient(_app())
    response = client.get("/ping", headers={REQUEST_ID_HEADER: "bad id with spaces"})
    assert response.headers.get(REQUEST_ID_HEADER) != "bad id with spaces"
    assert response.headers.get(REQUEST_ID_HEADER)


def test_get_request_id_none_outside_request() -> None:
    assert get_request_id() is None


def test_inference_client_attaches_auth_and_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization")
        captured["rid"] = request.headers.get(REQUEST_ID_HEADER)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def _factory(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)

    token = request_context._request_id_var.set("req-test-123")
    try:
        asyncio.run(inference_client.call_modelserver_predict({"text": "hi"}))
    finally:
        request_context._request_id_var.reset(token)

    expected = f"Bearer {settings.service_auth_token.get_secret_value()}"
    assert captured["auth"] == expected
    assert captured["rid"] == "req-test-123"
