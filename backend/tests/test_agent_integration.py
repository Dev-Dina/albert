"""Integration test: message → agent calls rag_search → returns a reply.

Uses a mock LLM so no real API key or network is needed in CI.
The mock simulates one tool-call round-trip:
  turn 1 → LLM returns tool_calls=[rag_search(...)]
  turn 2 → LLM returns stop with a plain text reply
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.adapters.llm import LLMAdapter
from app.services.agent import run_agent


def _make_tool_call_response(query: str) -> MagicMock:
    """Fake LLM response that requests rag_search."""
    tc = MagicMock()
    tc.id = "call_001"
    tc.function.name = "rag_search"
    tc.function.arguments = json.dumps({"query": query})

    msg = MagicMock()
    msg.tool_calls = [tc]
    msg.model_dump.return_value = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_001",
                "type": "function",
                "function": {"name": "rag_search", "arguments": json.dumps({"query": query})},
            }
        ],
    }

    choice = MagicMock()
    choice.finish_reason = "tool_calls"
    choice.message = msg

    response = MagicMock()
    response.choices = [choice]
    return response


def _make_stop_response(reply: str) -> MagicMock:
    """Fake LLM response that returns a plain text reply."""
    msg = MagicMock()
    msg.content = reply
    msg.tool_calls = None

    choice = MagicMock()
    choice.finish_reason = "stop"
    choice.message = msg

    response = MagicMock()
    response.choices = [choice]
    return response


@pytest.mark.asyncio
async def test_agent_calls_rag_search_and_returns_reply() -> None:
    """Send a message; agent calls rag_search once, then returns a reply."""
    llm = MagicMock(spec=LLMAdapter)
    llm.chat = AsyncMock(side_effect=[
        _make_tool_call_response("opening hours"),
        _make_stop_response("We are open Monday to Friday, 9am–5pm."),
    ])

    result = await run_agent(
        tenant_id="tenant-abc",
        conversation_id="conv-001",
        user_message="What are your opening hours?",
        llm=llm,
    )

    assert result.escalated is False
    assert result.reply == "We are open Monday to Friday, 9am–5pm."
    assert "rag_search" in result.tool_calls
    assert result.iterations_used == 2


@pytest.mark.asyncio
async def test_agent_auto_escalates_when_max_iterations_exceeded(monkeypatch) -> None:
    """When every LLM turn returns tool_calls, the loop hits max_iterations and escalates."""
    monkeypatch.setattr("app.services.agent.settings.agent_max_iterations", 2)

    llm = MagicMock(spec=LLMAdapter)
    llm.chat = AsyncMock(return_value=_make_tool_call_response("query"))

    result = await run_agent(
        tenant_id="tenant-abc",
        conversation_id="conv-002",
        user_message="Keep searching forever.",
        llm=llm,
    )

    assert result.escalated is True
    assert result.iterations_used == 2
