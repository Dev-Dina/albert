"""End-to-end widget chat: token verify → router → agent → guardrails → response.

Exercises the full route wiring without a live DB, Redis, modelserver, or
guardrails sidecar by overriding app dependencies and patching external calls.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.core.security import mint_widget_session_token
from app.main import app
from app.schemas.router import RouterDecision
from app.services.agent import AgentResult
from app.services.tenant_runtime import TenantRuntimeConfig

client = TestClient(app)

_DEFAULT_RUNTIME = TenantRuntimeConfig(
    business_name="the business", persona="Albert", tenant_rails=None
)


def _runtime_patch():
    return patch(
        "app.api.routes.widget_chat.load_runtime_config",
        new=AsyncMock(return_value=_DEFAULT_RUNTIME),
    )

_TENANT_A = uuid.uuid4()
_WIDGET_A = uuid.uuid4()
_PUBLIC_ID_A = "Acm" + "1" * 19
_ORIGIN = "http://localhost:8080"
_KEY = b"dev-tenant-A-signing-key-bytes-!"

_MOCK_REPLY = "We are open Monday to Friday, 9am–5pm."

_FAQ_DECISION = RouterDecision(
    action="agent", label="faq_rag", confidence=0.95, routed_to="agent"
)
_SPAM_DECISION = RouterDecision(
    action="direct", label="spam", confidence=0.99, routed_to="router", reply=None, handler="drop"
)
_MOCK_AGENT_RESULT = AgentResult(reply=_MOCK_REPLY, escalated=False, iterations_used=1)


class _FakeAgentDb:
    async def execute(self, *args, **kwargs):
        return None

    async def commit(self):
        return None


async def _null_db_gen(*args, **kwargs):
    yield _FakeAgentDb()


def _wire_dependencies() -> str:
    """Stub get_widget_session and app.state for tenant A."""
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
            expires_at=9999999999,
        )

    app.dependency_overrides[deps.get_widget_session] = _override

    app.state.redis = AsyncMock()
    app.state.redis.get = AsyncMock(return_value=None)
    app.state.redis.setex = AsyncMock()
    app.state.llm = AsyncMock()
    app.state.embedder = AsyncMock()
    app.state.reranker = AsyncMock()

    return token


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_chat_round_trip_returns_assistant_message() -> None:
    token = _wire_dependencies()

    with (
        _runtime_patch(),
        patch(
            "app.api.routes.widget_chat._guardrails_check",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "app.api.routes.widget_chat.router_service.classify_and_route",
            new=AsyncMock(return_value=_FAQ_DECISION),
        ),
        patch(
            "app.api.routes.widget_chat.get_tenant_db",
            new=_null_db_gen,
        ),
        patch(
            "app.api.routes.widget_chat.run_agent",
            new=AsyncMock(return_value=_MOCK_AGENT_RESULT),
        ),
    ):
        response = client.post(
            "/api/v1/widget/chat",
            headers={"Authorization": f"Bearer {token}", "Origin": _ORIGIN},
            json={"message": "What are your hours?"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["message"] == _MOCK_REPLY
    conv_id = uuid.UUID(body["conversation_id"])

    # Second turn with same conversation_id must be preserved.
    with (
        _runtime_patch(),
        patch(
            "app.api.routes.widget_chat._guardrails_check",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "app.api.routes.widget_chat.router_service.classify_and_route",
            new=AsyncMock(return_value=_FAQ_DECISION),
        ),
        patch(
            "app.api.routes.widget_chat.get_tenant_db",
            new=_null_db_gen,
        ),
        patch(
            "app.api.routes.widget_chat.run_agent",
            new=AsyncMock(return_value=_MOCK_AGENT_RESULT),
        ),
    ):
        response2 = client.post(
            "/api/v1/widget/chat",
            headers={"Authorization": f"Bearer {token}", "Origin": _ORIGIN},
            json={"message": "Follow up", "conversation_id": str(conv_id)},
        )

    assert response2.status_code == 200
    assert response2.json()["conversation_id"] == str(conv_id)


def test_guardrails_input_block_returns_400() -> None:
    token = _wire_dependencies()

    with (
        _runtime_patch(),
        patch("app.api.routes.widget_chat.get_tenant_db", new=_null_db_gen),
        patch(
            "app.api.routes.widget_chat._guardrails_check",
            new=AsyncMock(return_value=False),
        ),
    ):
        response = client.post(
            "/api/v1/widget/chat",
            headers={"Authorization": f"Bearer {token}", "Origin": _ORIGIN},
            json={"message": "blocked message"},
        )

    assert response.status_code == 400


def test_spam_label_returns_400() -> None:
    token = _wire_dependencies()

    with (
        _runtime_patch(),
        patch("app.api.routes.widget_chat.get_tenant_db", new=_null_db_gen),
        patch(
            "app.api.routes.widget_chat._guardrails_check",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "app.api.routes.widget_chat.router_service.classify_and_route",
            new=AsyncMock(return_value=_SPAM_DECISION),
        ),
    ):
        response = client.post(
            "/api/v1/widget/chat",
            headers={"Authorization": f"Bearer {token}", "Origin": _ORIGIN},
            json={"message": "BUY NOW"},
        )

    assert response.status_code == 400
