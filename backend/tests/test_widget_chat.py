"""Contract tests for POST /api/v1/widget/chat (US1 happy path stub)."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.core.security import mint_widget_session_token
from app.main import app

client = TestClient(app)


_TENANT_ID = uuid.uuid4()
_WIDGET_ID = uuid.uuid4()
_PUBLIC_WIDGET_ID = "Acm" + "Y" * 19
_ORIGIN = "http://localhost:8080"
_KEY_MATERIAL = b"dev-tenant-signing-key-bytes-32!"


def _mint_token() -> str:
    return mint_widget_session_token(
        tenant_id=_TENANT_ID,
        widget_id=_WIDGET_ID,
        public_widget_id=_PUBLIC_WIDGET_ID,
        origin=_ORIGIN,
        key_version=1,
        key_material=_KEY_MATERIAL,
    )


def _wire_widget_session_dep() -> None:
    """Stub the get_widget_session dep so the chat route runs without DB/Vault."""
    from app.api import deps
    from app.core.security import WidgetSessionClaims

    async def _override():
        yield WidgetSessionClaims(
            tenant_id=_TENANT_ID,
            widget_id=_WIDGET_ID,
            public_widget_id=_PUBLIC_WIDGET_ID,
            key_version=1,
            origin=_ORIGIN,
            issued_at=0,
            expires_at=0,
        )

    app.dependency_overrides[deps.get_widget_session] = _override


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_chat_happy_path_returns_echo() -> None:
    _wire_widget_session_dep()
    response = client.post(
        "/api/v1/widget/chat",
        headers={"Authorization": f"Bearer {_mint_token()}"},
        json={"message": "Hello"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["message"].startswith("You said:")
    assert "Hello" in body["message"]
    uuid.UUID(body["conversation_id"])


def test_chat_missing_token_returns_401() -> None:
    """No override: real get_widget_session runs and rejects missing Bearer."""
    response = client.post(
        "/api/v1/widget/chat",
        json={"message": "Hello"},
    )
    assert response.status_code == 401


def test_chat_body_with_tenant_id_is_rejected_at_schema_layer() -> None:
    """FR-009: chat request schema forbids tenant_id (extra='forbid')."""
    _wire_widget_session_dep()
    response = client.post(
        "/api/v1/widget/chat",
        headers={"Authorization": f"Bearer {_mint_token()}"},
        json={
            "message": "Hi",
            "tenant_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 422


def test_chat_message_too_long_returns_422() -> None:
    _wire_widget_session_dep()
    response = client.post(
        "/api/v1/widget/chat",
        headers={"Authorization": f"Bearer {_mint_token()}"},
        json={"message": "x" * 5000},
    )
    assert response.status_code == 422
