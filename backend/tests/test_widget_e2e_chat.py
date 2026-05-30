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


# --- T003 (US1): Approach A — chat authorizes on token alone, regardless of
# the request Origin. These exercise the REAL get_widget_session dependency (NOT
# overridden) so the removal of the deps.py Origin re-check is genuinely tested.


def _wire_real_widget_session_dependency() -> str:
    """Wire the real ``get_widget_session`` path (DB + Vault + active key stubbed)
    and return a valid token whose Origin is the backend origin and NOT on the
    customer allowlist. ``exists_for_tenant`` is stubbed to always refuse, proving
    Approach A no longer consults it on the request path.
    """
    from app.api import deps
    from app.clients import vault_client
    from app.db.session import get_db
    from app.repositories import allowed_origin_repo

    class _FakeSession:
        async def execute(self, *args, **kwargs):
            class _R:
                def scalar_one_or_none(self_inner):
                    return None
            return _R()

    async def _fake_get_db():
        yield _FakeSession()

    async def _fake_read_key(tenant_id):
        return _KEY

    async def _fake_active_key(db, tenant_id):
        class _Active:
            version = 1
        return _Active()

    async def _never_allowed(session, tenant_id, origin):
        # Origin intentionally NOT on the allowlist; Approach A must ignore it.
        return False

    app.dependency_overrides[get_db] = _fake_get_db
    vault_client.read_tenant_widget_signing_key = _fake_read_key  # type: ignore[assignment]
    deps._fetch_active_key_version = _fake_active_key  # type: ignore[assignment]
    allowed_origin_repo.exists_for_tenant = _never_allowed  # type: ignore[assignment]

    app.state.redis = AsyncMock()
    app.state.redis.get = AsyncMock(return_value=None)
    app.state.redis.setex = AsyncMock()
    app.state.llm = AsyncMock()
    app.state.embedder = AsyncMock()
    app.state.reranker = AsyncMock()

    return mint_widget_session_token(
        tenant_id=_TENANT_A,
        widget_id=_WIDGET_A,
        public_widget_id=_PUBLIC_ID_A,
        origin="http://localhost:8000",
        key_version=1,
        key_material=_KEY,
    )


def _chat_route_patches():
    return (
        _runtime_patch(),
        patch(
            "app.api.routes.widget_chat._guardrails_check",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "app.api.routes.widget_chat.router_service.classify_and_route",
            new=AsyncMock(return_value=_FAQ_DECISION),
        ),
        patch("app.api.routes.widget_chat.get_tenant_db", new=_null_db_gen),
        patch(
            "app.api.routes.widget_chat.run_agent",
            new=AsyncMock(return_value=_MOCK_AGENT_RESULT),
        ),
    )


def test_chat_succeeds_with_backend_origin_via_real_dependency() -> None:
    """C-C1: a valid token authorizes chat even when the request Origin is the
    backend origin and NOT on the customer allowlist.

    Fails against current code (401 from the removed Origin re-check); passes
    after the deps.py Origin block is dropped.
    """
    token = _wire_real_widget_session_dependency()
    p = _chat_route_patches()
    with p[0], p[1], p[2], p[3], p[4]:
        response = client.post(
            "/api/v1/widget/chat",
            headers={
                "Authorization": f"Bearer {token}",
                "Origin": "http://localhost:8000",
            },
            json={"message": "What are your hours?"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["message"] == _MOCK_REPLY


def test_chat_succeeds_with_no_origin_header_via_real_dependency() -> None:
    """C-C1: a valid token authorizes chat even with NO Origin header at all
    (Approach A drops the request-time Origin requirement on the chat path).

    Fails against current code (401 on missing Origin); passes after removal.
    """
    token = _wire_real_widget_session_dependency()
    p = _chat_route_patches()
    with p[0], p[1], p[2], p[3], p[4]:
        response = client.post(
            "/api/v1/widget/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "What are your hours?"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["message"] == _MOCK_REPLY


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
