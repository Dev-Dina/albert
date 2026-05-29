"""Unit tests for the cheap-path workflow dispatch (Phase 6.3)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.router import RouterDecision
from app.services.workflow import dispatch, extract_contact

_TID = "11111111-1111-1111-1111-111111111111"
_CID = "22222222-2222-2222-2222-222222222222"


@asynccontextmanager
async def _fake_db_ctx(tenant_id: str):
    yield None


def _decision(handler: str, label: str = "x") -> RouterDecision:
    return RouterDecision(action="direct", label=label, confidence=0.95, routed_to="workflow", handler=handler)


async def _run(decision, message: str, **over):
    kwargs = dict(
        message=message,
        tenant_id=_TID,
        conversation_id=_CID,
        db_ctx=_fake_db_ctx,
        redis=None,
        embedder=MagicMock(),
        reranker=MagicMock(),
    )
    kwargs.update(over)
    return await dispatch(decision, **kwargs)


def test_extract_contact_email():
    assert extract_contact("reach me at sales@acme.com please") == "sales@acme.com"


def test_extract_contact_phone():
    assert extract_contact("call +1 (415) 555-2671 anytime") == "+1 (415) 555-2671"


def test_extract_contact_none():
    assert extract_contact("I just want to chat") is None


@pytest.mark.asyncio
async def test_dispatch_drop():
    res = await _run(_decision("drop", "spam"), "BUY NOW")
    assert res.dropped is True
    assert res.reply is None


@pytest.mark.asyncio
async def test_dispatch_rag_returns_extractive_answer():
    with patch(
        "app.services.workflow.rag_search",
        new=AsyncMock(return_value=[{"chunk_id": "c1", "content": "We are open 9am-5pm.", "score": 1.0}]),
    ) as rag:
        res = await _run(_decision("rag", "faq_rag"), "what are your hours?")
    assert res.handled_by == "workflow"
    assert "We are open 9am-5pm." in res.reply
    rag.assert_awaited_once()
    assert rag.await_args.kwargs["tenant_id"] == _TID


@pytest.mark.asyncio
async def test_dispatch_rag_miss_falls_back_to_agent():
    with patch("app.services.workflow.rag_search", new=AsyncMock(return_value=[])):
        res = await _run(_decision("rag", "faq_rag"), "obscure question")
    assert res.reply is None
    assert res.handled_by == "agent"


@pytest.mark.asyncio
async def test_dispatch_rag_missing_adapters_falls_back():
    with patch("app.services.workflow.rag_search", new=AsyncMock()) as rag:
        res = await _run(_decision("rag", "faq_rag"), "q", embedder=None)
    assert res.reply is None
    assert res.handled_by == "agent"
    rag.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_lead_with_contact_calls_capture_lead():
    with patch(
        "app.services.workflow.capture_lead",
        new=AsyncMock(return_value={"lead_id": "x", "status": "captured"}),
    ) as cap:
        res = await _run(_decision("lead", "lead_capture"), "email me at sales@acme.com")
    assert res.handled_by == "workflow"
    assert "sales@acme.com" in res.reply
    cap.assert_awaited_once()
    assert cap.await_args.kwargs["tenant_id"] == _TID
    assert cap.await_args.kwargs["contact"] == "sales@acme.com"


@pytest.mark.asyncio
async def test_dispatch_lead_without_contact_falls_back_to_agent():
    with patch("app.services.workflow.capture_lead", new=AsyncMock()) as cap:
        res = await _run(_decision("lead", "lead_capture"), "I want to buy something")
    assert res.reply is None
    assert res.handled_by == "agent"
    cap.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_escalate_calls_escalate():
    with patch(
        "app.services.workflow.escalate",
        new=AsyncMock(return_value={"ticket_id": _CID, "status": "escalated"}),
    ) as esc:
        res = await _run(_decision("escalate", "human_escalate"), "let me talk to a human")
    assert res.handled_by == "workflow"
    assert res.reply
    esc.assert_awaited_once()
    assert esc.await_args.kwargs["tenant_id"] == _TID


@pytest.mark.asyncio
async def test_dispatch_agent_signals_fallback():
    res = await _run(_decision("agent", "other_agent"), "tell me a story")
    assert res.reply is None
    assert res.handled_by == "agent"
    assert res.dropped is False
