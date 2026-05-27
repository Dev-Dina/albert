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


def test_chat_body_with_foreign_tenant_id_is_ignored_and_logged(caplog) -> None:
    """T048 / FR-009: a `tenant_id` field in the body is dropped on parse and
    the request is served under the token's tenant. The event is logged as
    `body_tenant_id_ignored` (no raw tenant ids per FR-015c)."""
    _wire_widget_session_dep()
    foreign_tenant_id = str(uuid.uuid4())
    with caplog.at_level("WARNING"):
        response = client.post(
            "/api/v1/widget/chat",
            headers={"Authorization": f"Bearer {_mint_token()}"},
            json={
                "message": "Hi",
                "tenant_id": foreign_tenant_id,
            },
        )
    assert response.status_code == 200, response.text
    # The body field was ignored — request was served under the token's tenant.
    body = response.json()
    assert "Hi" in body["message"]
    # A structured log entry was emitted for operator visibility.
    assert any("body_tenant_id_ignored" in record.message for record in caplog.records)
    # The raw foreign tenant_id MUST NOT appear in any log line (FR-015c).
    for record in caplog.records:
        assert foreign_tenant_id not in record.getMessage()


def test_chat_message_too_long_returns_422() -> None:
    _wire_widget_session_dep()
    response = client.post(
        "/api/v1/widget/chat",
        headers={"Authorization": f"Bearer {_mint_token()}"},
        json={"message": "x" * 5000},
    )
    assert response.status_code == 422
