"""Contract tests for POST /api/v1/widget/chat."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.core.security import mint_widget_session_token
from app.main import app
from app.schemas.router import RouterDecision
from app.services.agent import AgentResult
from app.services.tenant_runtime import TenantRuntimeConfig

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


class _FakeAgentDb:
    """Minimal stand-in for the agent-path tenant session (ensure_conversation + commit)."""

    async def execute(self, *args, **kwargs):
        return None

    async def commit(self):
        return None


async def _null_db_gen(*args, **kwargs):
    yield _FakeAgentDb()


_AGENT_REPLY = "Here is the answer."
_MOCK_AGENT_RESULT = AgentResult(reply=_AGENT_REPLY, escalated=False, iterations_used=1)
_FAQ_DECISION = RouterDecision(
    action="agent", label="faq_rag", confidence=0.95, routed_to="agent"
)


def _patch_chat_pipeline():
    """Context manager that patches all external calls in the widget chat route."""
    app.state.redis = AsyncMock()
    app.state.redis.get = AsyncMock(return_value=None)
    app.state.redis.setex = AsyncMock()
    app.state.llm = AsyncMock()
    app.state.embedder = AsyncMock()
    app.state.reranker = AsyncMock()
    from contextlib import ExitStack
    from unittest.mock import patch as _patch
    stack = ExitStack()
    stack.enter_context(_patch("app.api.routes.widget_chat._guardrails_check", new=AsyncMock(return_value=True)))
    stack.enter_context(_patch("app.api.routes.widget_chat.router_service.classify_and_route", new=AsyncMock(return_value=_FAQ_DECISION)))
    stack.enter_context(_patch("app.api.routes.widget_chat.get_tenant_db", new=_null_db_gen))
    stack.enter_context(_patch("app.api.routes.widget_chat.run_agent", new=AsyncMock(return_value=_MOCK_AGENT_RESULT)))
    stack.enter_context(
        _patch(
            "app.api.routes.widget_chat.load_runtime_config",
            new=AsyncMock(
                return_value=TenantRuntimeConfig(
                    business_name="the business", persona="Albert", tenant_rails=None
                )
            ),
        )
    )
    return stack


def test_chat_happy_path_returns_assistant_reply() -> None:
    _wire_widget_session_dep()
    with _patch_chat_pipeline():
        response = client.post(
            "/api/v1/widget/chat",
            headers={"Authorization": f"Bearer {_mint_token()}"},
            json={"message": "Hello"},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["message"] == _AGENT_REPLY
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
    with caplog.at_level("WARNING"), _patch_chat_pipeline():
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
    assert body["message"] == _AGENT_REPLY
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


def test_chat_passes_tenant_persona_and_business_name_to_agent() -> None:
    """Phase 6.2B: the agent runs with the tenant's persona/business_name, not defaults."""
    _wire_widget_session_dep()
    from contextlib import ExitStack
    from unittest.mock import patch as _patch

    app.state.redis = AsyncMock()
    app.state.redis.get = AsyncMock(return_value=None)
    app.state.redis.setex = AsyncMock()
    app.state.llm = AsyncMock()
    app.state.embedder = AsyncMock()
    app.state.reranker = AsyncMock()

    run_agent_mock = AsyncMock(return_value=_MOCK_AGENT_RESULT)
    runtime = TenantRuntimeConfig(
        business_name="Acme Inc", persona="Acme Bot", tenant_rails=None
    )
    with ExitStack() as stack:
        stack.enter_context(_patch("app.api.routes.widget_chat._guardrails_check", new=AsyncMock(return_value=True)))
        stack.enter_context(_patch("app.api.routes.widget_chat.router_service.classify_and_route", new=AsyncMock(return_value=_FAQ_DECISION)))
        stack.enter_context(_patch("app.api.routes.widget_chat.get_tenant_db", new=_null_db_gen))
        stack.enter_context(_patch("app.api.routes.widget_chat.load_runtime_config", new=AsyncMock(return_value=runtime)))
        stack.enter_context(_patch("app.api.routes.widget_chat.run_agent", new=run_agent_mock))
        response = client.post(
            "/api/v1/widget/chat",
            headers={"Authorization": f"Bearer {_mint_token()}"},
            json={"message": "Hello"},
        )

    assert response.status_code == 200, response.text
    run_agent_mock.assert_awaited_once()
    kwargs = run_agent_mock.await_args.kwargs
    assert kwargs["persona"] == "Acme Bot"
    assert kwargs["business_name"] == "Acme Inc"


def test_chat_forwards_tenant_rails_to_guardrails() -> None:
    """Phase 6.2B: tenant rails are sent to both guardrails (input + output) checks."""
    _wire_widget_session_dep()
    from contextlib import ExitStack
    from unittest.mock import patch as _patch

    app.state.redis = AsyncMock()
    app.state.redis.get = AsyncMock(return_value=None)
    app.state.redis.setex = AsyncMock()
    app.state.llm = AsyncMock()
    app.state.embedder = AsyncMock()
    app.state.reranker = AsyncMock()

    rails = {"blocked_topics": ["refunds"]}
    runtime = TenantRuntimeConfig(business_name="Acme Inc", persona="Acme Bot", tenant_rails=rails)
    guardrails_mock = AsyncMock(return_value=True)
    with ExitStack() as stack:
        stack.enter_context(_patch("app.api.routes.widget_chat._guardrails_check", new=guardrails_mock))
        stack.enter_context(_patch("app.api.routes.widget_chat.router_service.classify_and_route", new=AsyncMock(return_value=_FAQ_DECISION)))
        stack.enter_context(_patch("app.api.routes.widget_chat.get_tenant_db", new=_null_db_gen))
        stack.enter_context(_patch("app.api.routes.widget_chat.load_runtime_config", new=AsyncMock(return_value=runtime)))
        stack.enter_context(_patch("app.api.routes.widget_chat.run_agent", new=AsyncMock(return_value=_MOCK_AGENT_RESULT)))
        response = client.post(
            "/api/v1/widget/chat",
            headers={"Authorization": f"Bearer {_mint_token()}"},
            json={"message": "Hello"},
        )

    assert response.status_code == 200, response.text
    # input check + output check both received the tenant rails.
    endpoints = [c.args[0] for c in guardrails_mock.await_args_list]
    assert endpoints == ["input", "output"]
    for call in guardrails_mock.await_args_list:
        assert call.args[2] == rails  # tenant_rails forwarded


# ---------------------------------------------------------------------------
# Phase 6.3: classifier-driven cheap workflow paths (no agent for easy cases)
# ---------------------------------------------------------------------------

_DEFAULT_RUNTIME = TenantRuntimeConfig(business_name="Acme Inc", persona="Acme Bot", tenant_rails=None)


def _decision(handler: str, label: str) -> RouterDecision:
    action = "agent" if handler == "agent" else "direct"
    routed = {"drop": "router", "agent": "agent"}.get(handler, "workflow")
    return RouterDecision(action=action, label=label, confidence=0.95, routed_to=routed, handler=handler)


def _set_app_state() -> None:
    app.state.redis = AsyncMock()
    app.state.redis.get = AsyncMock(return_value=None)
    app.state.redis.setex = AsyncMock()
    app.state.llm = AsyncMock()
    app.state.embedder = AsyncMock()
    app.state.reranker = AsyncMock()


def _post(message: str):
    return client.post(
        "/api/v1/widget/chat",
        headers={"Authorization": f"Bearer {_mint_token()}"},
        json={"message": message},
    )


def test_spam_handler_drops_without_calling_agent() -> None:
    _wire_widget_session_dep()
    _set_app_state()
    from contextlib import ExitStack
    from unittest.mock import patch as _patch

    run_agent_mock = AsyncMock(return_value=_MOCK_AGENT_RESULT)
    with ExitStack() as stack:
        stack.enter_context(_patch("app.api.routes.widget_chat._guardrails_check", new=AsyncMock(return_value=True)))
        stack.enter_context(_patch("app.api.routes.widget_chat.load_runtime_config", new=AsyncMock(return_value=_DEFAULT_RUNTIME)))
        stack.enter_context(_patch("app.api.routes.widget_chat.get_tenant_db", new=_null_db_gen))
        stack.enter_context(_patch("app.api.routes.widget_chat.router_service.classify_and_route", new=AsyncMock(return_value=_decision("drop", "spam"))))
        stack.enter_context(_patch("app.api.routes.widget_chat.run_agent", new=run_agent_mock))
        response = _post("BUY CHEAP NOW")

    assert response.status_code == 400
    run_agent_mock.assert_not_awaited()


def test_faq_handler_uses_rag_without_agent() -> None:
    _wire_widget_session_dep()
    _set_app_state()
    from contextlib import ExitStack
    from unittest.mock import patch as _patch

    run_agent_mock = AsyncMock(return_value=_MOCK_AGENT_RESULT)
    guardrails_mock = AsyncMock(return_value=True)
    rag_mock = AsyncMock(return_value=[{"chunk_id": "c1", "content": "We are open 9am to 5pm.", "score": 1.0}])
    with ExitStack() as stack:
        stack.enter_context(_patch("app.api.routes.widget_chat._guardrails_check", new=guardrails_mock))
        stack.enter_context(_patch("app.api.routes.widget_chat.load_runtime_config", new=AsyncMock(return_value=_DEFAULT_RUNTIME)))
        stack.enter_context(_patch("app.api.routes.widget_chat.get_tenant_db", new=_null_db_gen))
        stack.enter_context(_patch("app.api.routes.widget_chat.router_service.classify_and_route", new=AsyncMock(return_value=_decision("rag", "faq_rag"))))
        stack.enter_context(_patch("app.services.workflow.rag_search", new=rag_mock))
        stack.enter_context(_patch("app.api.routes.widget_chat.run_agent", new=run_agent_mock))
        response = _post("what are your hours?")

    assert response.status_code == 200, response.text
    assert "We are open 9am to 5pm." in response.json()["message"]
    run_agent_mock.assert_not_awaited()
    # RAG ran with the token's tenant; guardrails wrapped input + output.
    assert rag_mock.await_args.kwargs["tenant_id"] == str(_TENANT_ID)
    assert [c.args[0] for c in guardrails_mock.await_args_list] == ["input", "output"]


def test_lead_handler_calls_capture_lead_without_agent() -> None:
    _wire_widget_session_dep()
    _set_app_state()
    from contextlib import ExitStack
    from unittest.mock import patch as _patch

    run_agent_mock = AsyncMock(return_value=_MOCK_AGENT_RESULT)
    capture_mock = AsyncMock(return_value={"lead_id": "x", "status": "captured"})
    with ExitStack() as stack:
        stack.enter_context(_patch("app.api.routes.widget_chat._guardrails_check", new=AsyncMock(return_value=True)))
        stack.enter_context(_patch("app.api.routes.widget_chat.load_runtime_config", new=AsyncMock(return_value=_DEFAULT_RUNTIME)))
        stack.enter_context(_patch("app.api.routes.widget_chat.get_tenant_db", new=_null_db_gen))
        stack.enter_context(_patch("app.api.routes.widget_chat.router_service.classify_and_route", new=AsyncMock(return_value=_decision("lead", "lead_capture"))))
        stack.enter_context(_patch("app.services.workflow.capture_lead", new=capture_mock))
        stack.enter_context(_patch("app.api.routes.widget_chat.run_agent", new=run_agent_mock))
        response = _post("please have sales email me at buyer@acme.com")

    assert response.status_code == 200, response.text
    run_agent_mock.assert_not_awaited()
    capture_mock.assert_awaited_once()
    assert capture_mock.await_args.kwargs["tenant_id"] == str(_TENANT_ID)
    assert capture_mock.await_args.kwargs["contact"] == "buyer@acme.com"


def test_escalate_handler_calls_escalate_without_agent() -> None:
    _wire_widget_session_dep()
    _set_app_state()
    from contextlib import ExitStack
    from unittest.mock import patch as _patch

    run_agent_mock = AsyncMock(return_value=_MOCK_AGENT_RESULT)
    escalate_mock = AsyncMock(return_value={"ticket_id": "c", "status": "escalated"})
    with ExitStack() as stack:
        stack.enter_context(_patch("app.api.routes.widget_chat._guardrails_check", new=AsyncMock(return_value=True)))
        stack.enter_context(_patch("app.api.routes.widget_chat.load_runtime_config", new=AsyncMock(return_value=_DEFAULT_RUNTIME)))
        stack.enter_context(_patch("app.api.routes.widget_chat.get_tenant_db", new=_null_db_gen))
        stack.enter_context(_patch("app.api.routes.widget_chat.router_service.classify_and_route", new=AsyncMock(return_value=_decision("escalate", "human_escalate"))))
        stack.enter_context(_patch("app.services.workflow.escalate", new=escalate_mock))
        stack.enter_context(_patch("app.api.routes.widget_chat.run_agent", new=run_agent_mock))
        response = _post("I want to talk to a human")

    assert response.status_code == 200, response.text
    run_agent_mock.assert_not_awaited()
    escalate_mock.assert_awaited_once()
    assert escalate_mock.await_args.kwargs["tenant_id"] == str(_TENANT_ID)


def test_agent_handler_calls_run_agent() -> None:
    _wire_widget_session_dep()
    _set_app_state()
    from contextlib import ExitStack
    from unittest.mock import patch as _patch

    run_agent_mock = AsyncMock(return_value=_MOCK_AGENT_RESULT)
    with ExitStack() as stack:
        stack.enter_context(_patch("app.api.routes.widget_chat._guardrails_check", new=AsyncMock(return_value=True)))
        stack.enter_context(_patch("app.api.routes.widget_chat.load_runtime_config", new=AsyncMock(return_value=_DEFAULT_RUNTIME)))
        stack.enter_context(_patch("app.api.routes.widget_chat.get_tenant_db", new=_null_db_gen))
        stack.enter_context(_patch("app.api.routes.widget_chat.router_service.classify_and_route", new=AsyncMock(return_value=_decision("agent", "other_agent"))))
        stack.enter_context(_patch("app.api.routes.widget_chat.run_agent", new=run_agent_mock))
        response = _post("tell me something interesting")

    assert response.status_code == 200, response.text
    assert response.json()["message"] == _AGENT_REPLY
    run_agent_mock.assert_awaited_once()
