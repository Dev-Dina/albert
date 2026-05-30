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
async def test_agent_recovers_from_empty_stop_with_no_tools_synthesis() -> None:
    """An empty 'stop' after a tool call triggers a no-tools synthesis turn that
    produces the answer from gathered context — instead of escalating (#2)."""
    llm = MagicMock(spec=LLMAdapter)
    llm.chat = AsyncMock(side_effect=[
        _make_tool_call_response("acme offerings"),          # iter 1: tool call
        _make_stop_response(""),                             # iter 2: empty stop
        _make_stop_response("Acme offers managed cloud hosting and Kubernetes."),  # synthesis
    ])

    result = await run_agent(
        tenant_id="tenant-abc",
        conversation_id="conv-003",
        user_message="what does acme offer",
        llm=llm,
    )

    assert result.escalated is False
    assert result.reply == "Acme offers managed cloud hosting and Kubernetes."
    # The recovery turn MUST drop tools to force a plain-text answer.
    assert llm.chat.call_args_list[-1].kwargs["tools"] is None


@pytest.mark.asyncio
async def test_agent_escalates_when_synthesis_also_empty() -> None:
    """If even the forced synthesis turn is empty, the agent still escalates."""
    llm = MagicMock(spec=LLMAdapter)
    llm.chat = AsyncMock(side_effect=[
        _make_tool_call_response("q"),
        _make_stop_response(""),   # empty stop
        _make_stop_response(""),   # synthesis also empty
    ])

    result = await run_agent(
        tenant_id="tenant-abc",
        conversation_id="conv-004",
        user_message="x",
        llm=llm,
    )

    assert result.escalated is True


@pytest.mark.asyncio
async def test_tool_result_message_carries_tool_name() -> None:
    """The tool-result message sent back to the LLM must carry the tool's name so
    Gemini binds the function_response to its function_call (#3)."""
    llm = MagicMock(spec=LLMAdapter)
    llm.chat = AsyncMock(side_effect=[
        _make_tool_call_response("q"),
        _make_stop_response("here is the answer"),
    ])

    await run_agent(
        tenant_id="tenant-abc",
        conversation_id="conv-005",
        user_message="x",
        llm=llm,
    )

    # The 2nd LLM call carries the tool result; it must name the tool.
    second_call_messages = llm.chat.call_args_list[1].kwargs["messages"]
    tool_msgs = [m for m in second_call_messages if m.get("role") == "tool"]
    assert tool_msgs, "expected a tool-result message in the follow-up turn"
    assert tool_msgs[0]["name"] == "rag_search"


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
