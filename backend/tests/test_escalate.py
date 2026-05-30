"""Escalation tool + dispatcher tests.

Regression coverage for the bug where the agent dispatcher passed
``conversation_id="unknown"`` (from LLM tool args) to ``escalate`` instead of
the trusted server-side conversation id, so escalations never persisted.

Trusted context rule: tenant_id + conversation_id come from the verified widget
session, never from the LLM. The model only supplies ``reason``/``summary``.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.agent import _dispatch_tool
from app.tools.escalate import escalate


# ---------------------------------------------------------------------------
# Fake AsyncSession for escalate persistence (no real DB)
# ---------------------------------------------------------------------------

class _FakeResult:
    def __init__(self, obj: object) -> None:
        self._obj = obj

    def scalar_one_or_none(self) -> object:
        return self._obj


class _FakeSession:
    """Minimal AsyncSession stand-in: no existing conversation, records adds."""

    def __init__(self, existing: object = None) -> None:
        self._existing = existing
        self.added: list = []
        self.flushed = False

    async def execute(self, *args, **kwargs) -> _FakeResult:
        return _FakeResult(self._existing)

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed = True


# ---------------------------------------------------------------------------
# escalate() persistence
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_escalate_with_valid_uuid_marks_conversation_escalated() -> None:
    tenant_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    db = _FakeSession(existing=None)

    result = await escalate(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        reason="Visitor wants a human.",
        db=db,
    )

    assert result["status"] == "escalated"
    assert result["ticket_id"] == conversation_id
    # A new conversation row was created and marked escalated, AND an escalation
    # record was persisted with the reason (feature 007, US3).
    statuses = [getattr(obj, "status", None) for obj in db.added]
    assert "escalated" in statuses  # the conversation row
    reasons = [getattr(obj, "reason", None) for obj in db.added]
    assert "Visitor wants a human." in reasons  # the escalation row
    assert db.flushed is True


@pytest.mark.asyncio
async def test_escalate_rejects_non_uuid_conversation_id() -> None:
    """A non-UUID (e.g. the old 'unknown' default) is controlled, not persisted."""
    result = await escalate(
        tenant_id=str(uuid.uuid4()),
        conversation_id="unknown",
        reason="x",
        db=_FakeSession(),
    )
    assert result["status"] == "invalid_id"


# ---------------------------------------------------------------------------
# dispatcher injects trusted conversation_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_escalate_injects_server_conversation_id(monkeypatch) -> None:
    """The dispatcher must pass the server-side conversation_id to escalate even
    when the LLM tool args omit it — never the literal 'unknown'."""
    captured: dict = {}

    async def _fake_escalate(**kwargs):
        captured.update(kwargs)
        return {"ticket_id": kwargs["conversation_id"], "status": "escalated"}

    monkeypatch.setattr("app.services.agent.escalate", _fake_escalate)

    tenant_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())

    await _dispatch_tool(
        tool_name="escalate",
        tool_args={"reason": "Visitor wants a human."},  # LLM omits conversation_id
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        db=_FakeSession(),
    )

    assert captured["conversation_id"] == conversation_id
    assert captured["conversation_id"] != "unknown"
    assert captured["tenant_id"] == tenant_id


@pytest.mark.asyncio
async def test_dispatch_escalate_ignores_llm_supplied_conversation_id(monkeypatch) -> None:
    """Even if the LLM forges a conversation_id/tenant_id in tool args, the
    dispatcher uses the trusted server-side context."""
    captured: dict = {}

    async def _fake_escalate(**kwargs):
        captured.update(kwargs)
        return {"ticket_id": kwargs["conversation_id"], "status": "escalated"}

    monkeypatch.setattr("app.services.agent.escalate", _fake_escalate)

    real_conv = str(uuid.uuid4())
    await _dispatch_tool(
        tool_name="escalate",
        tool_args={
            "reason": "hi",
            "conversation_id": "attacker-supplied",
            "tenant_id": "attacker-tenant",
        },
        tenant_id="trusted-tenant",
        conversation_id=real_conv,
        db=_FakeSession(),
    )

    assert captured["conversation_id"] == real_conv
    assert captured["tenant_id"] == "trusted-tenant"


@pytest.mark.asyncio
async def test_dispatch_escalate_falls_back_when_reason_missing(monkeypatch) -> None:
    """If the LLM omits reason, the dispatcher supplies a safe non-empty fallback
    (escalate's validator rejects empty reasons)."""
    captured: dict = {}

    async def _fake_escalate(**kwargs):
        captured.update(kwargs)
        return {"ticket_id": kwargs["conversation_id"], "status": "escalated"}

    monkeypatch.setattr("app.services.agent.escalate", _fake_escalate)

    await _dispatch_tool(
        tool_name="escalate",
        tool_args={},  # no reason
        tenant_id=str(uuid.uuid4()),
        conversation_id=str(uuid.uuid4()),
        db=_FakeSession(),
    )

    assert captured["reason"].strip() != ""
