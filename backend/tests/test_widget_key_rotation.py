"""Key-rotation invalidates outstanding tokens (T049, FR-010).

Issue a token at key version v1; rotate (so active version becomes v2 with new
material); the previously-issued token returns 401 on the next chat call.
After a re-exchange against the new active key, chat succeeds again.
"""

from __future__ import annotations

import uuid
from contextlib import ExitStack
from unittest.mock import AsyncMock
from unittest.mock import patch as _patch

from fastapi.testclient import TestClient

from app.core.security import mint_widget_session_token
from app.main import app
from app.schemas.router import RouterDecision
from app.services.agent import AgentResult

client = TestClient(app)


_TENANT_ID = uuid.uuid4()
_WIDGET_ID = uuid.uuid4()
_PUBLIC_WIDGET_ID = "Acm" + "R" * 19
_ORIGIN = "http://localhost:8080"
_KEY_V1 = b"dev-tenant-signing-key-v1-bytes!"
_KEY_V2 = b"dev-tenant-signing-key-v2-bytes!"


class _State:
    active_version: int = 1
    active_key: bytes = _KEY_V1


def _wire(state: _State) -> None:
    from app.api import deps
    from app.clients import vault_client
    from app.db.session import get_db
    from app.repositories import allowed_origin_repo

    class _FakeSession:
        async def execute(self, *args, **kwargs):
            _sql = str(args[0]).lower() if args else ""
            _active = "tenants.status" in _sql or "from tenants" in _sql
            class _R:
                def scalar_one_or_none(self_inner):
                    return "active" if _active else None
            return _R()

    async def _fake_get_db():
        yield _FakeSession()

    async def _fake_read_key(tenant_id):
        return state.active_key

    async def _fake_exists_for_tenant(session, tenant_id, origin):
        return True

    async def _fake_active_key(db, tenant_id):
        class _Active:
            version = state.active_version
        return _Active()

    app.dependency_overrides[get_db] = _fake_get_db
    vault_client.read_tenant_widget_signing_key = _fake_read_key  # type: ignore[assignment]
    allowed_origin_repo.exists_for_tenant = _fake_exists_for_tenant  # type: ignore[assignment]
    deps._fetch_active_key_version = _fake_active_key  # type: ignore[assignment]


def teardown_function() -> None:
    app.dependency_overrides.clear()


class _FakeAgentDb:
    async def execute(self, *args, **kwargs):
        return None

    async def commit(self):
        return None


async def _null_db_gen(*args, **kwargs):
    yield _FakeAgentDb()


_MOCK_AGENT_RESULT = AgentResult(reply="ok", escalated=False, iterations_used=1)
_FAQ_DECISION = RouterDecision(action="agent", label="faq_rag", confidence=0.9, routed_to="agent")


def _patch_chat_pipeline():
    app.state.redis = AsyncMock()
    app.state.redis.get = AsyncMock(return_value=None)
    app.state.redis.setex = AsyncMock()
    app.state.llm = AsyncMock()
    app.state.embedder = AsyncMock()
    app.state.reranker = AsyncMock()
    stack = ExitStack()
    stack.enter_context(_patch("app.api.routes.widget_chat._guardrails_check", new=AsyncMock(return_value=True)))
    stack.enter_context(_patch("app.api.routes.widget_chat.router_service.classify_and_route", new=AsyncMock(return_value=_FAQ_DECISION)))
    stack.enter_context(_patch("app.api.routes.widget_chat.get_tenant_db", new=_null_db_gen))
    stack.enter_context(_patch("app.api.routes.widget_chat.run_agent", new=AsyncMock(return_value=_MOCK_AGENT_RESULT)))
    return stack


def test_rotation_invalidates_prior_token() -> None:
    state = _State()
    _wire(state)

    token_v1 = mint_widget_session_token(
        tenant_id=_TENANT_ID,
        widget_id=_WIDGET_ID,
        public_widget_id=_PUBLIC_WIDGET_ID,
        origin=_ORIGIN,
        key_version=1,
        key_material=_KEY_V1,
    )

    with _patch_chat_pipeline():
        response = client.post(
            "/api/v1/widget/chat",
            headers={"Authorization": f"Bearer {token_v1}", "Origin": _ORIGIN},
            json={"message": "before rotation"},
        )
    assert response.status_code == 200, response.text

    # Rotate: active version → 2, material → KEY_V2.
    state.active_version = 2
    state.active_key = _KEY_V2

    response = client.post(
        "/api/v1/widget/chat",
        headers={"Authorization": f"Bearer {token_v1}", "Origin": _ORIGIN},
        json={"message": "after rotation"},
    )
    assert response.status_code == 401


def test_reexchange_after_rotation_succeeds() -> None:
    state = _State()
    state.active_version = 2
    state.active_key = _KEY_V2
    _wire(state)

    # A token freshly minted at v2 must verify.
    token_v2 = mint_widget_session_token(
        tenant_id=_TENANT_ID,
        widget_id=_WIDGET_ID,
        public_widget_id=_PUBLIC_WIDGET_ID,
        origin=_ORIGIN,
        key_version=2,
        key_material=_KEY_V2,
    )
    with _patch_chat_pipeline():
        response = client.post(
            "/api/v1/widget/chat",
            headers={"Authorization": f"Bearer {token_v2}", "Origin": _ORIGIN},
            json={"message": "fresh"},
        )
    assert response.status_code == 200
