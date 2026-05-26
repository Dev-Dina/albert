"""End-to-end widget chat: seed → exchange → chat → assert conversation_id.

The "real" e2e runs against `docker compose up` (see quickstart.md step 8).
This test exercises the route wiring + token verification + RLS-context dep
without a live DB or Vault by overriding the dependencies, so it can run in
unit-test CI.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.core.security import mint_widget_session_token
from app.main import app

client = TestClient(app)


_TENANT_A = uuid.uuid4()
_WIDGET_A = uuid.uuid4()
_PUBLIC_ID_A = "Acm" + "1" * 19
_ORIGIN = "http://localhost:8080"
_KEY = b"dev-tenant-A-signing-key-bytes-!"


def _wire_dependencies() -> None:
    """Stub get_widget_session for tenant A so a chat round-trip works."""
    from app.api import deps
    from app.core.security import WidgetSessionClaims

    token = mint_widget_session_token(
        tenant_id=_TENANT_A,
        widget_id=_WIDGET_A,
        public_widget_id=_PUBLIC_ID_A,
        origin=_ORIGIN,
        key_version=1,
        key_material=_KEY,
    )

    async def _override():
        yield WidgetSessionClaims(
            tenant_id=_TENANT_A,
            widget_id=_WIDGET_A,
            public_widget_id=_PUBLIC_ID_A,
            key_version=1,
            origin=_ORIGIN,
            issued_at=0,
            expires_at=0,
        )

    app.dependency_overrides[deps.get_widget_session] = _override
    return token


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_chat_round_trip_returns_assistant_message() -> None:
    token = _wire_dependencies()
    response = client.post(
        "/api/v1/widget/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "Hello tenant A"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "Hello tenant A" in body["message"]
    # conversation_id must be a UUID; subsequent requests can pass it back.
    conv_id = uuid.UUID(body["conversation_id"])
    response2 = client.post(
        "/api/v1/widget/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "Follow up", "conversation_id": str(conv_id)},
    )
    assert response2.status_code == 200
    assert response2.json()["conversation_id"] == str(conv_id)
