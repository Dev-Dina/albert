from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.schemas.router import RouterDecision
from app.services.router import classify_and_route


def _mock_response(label: str, confidence: float) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {"label": label, "confidence": confidence}
    resp.raise_for_status = MagicMock()
    return resp


def _setup_mock_client(mock_client_cls: MagicMock, label: str, confidence: float) -> MagicMock:
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=_mock_response(label, confidence))
    mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_client


@pytest.mark.asyncio
async def test_faq_rag_routes_to_agent():
    with patch("app.services.router.httpx.AsyncClient") as mock_client_cls:
        mock_client = _setup_mock_client(mock_client_cls, "faq_rag", 0.95)
        decision = await classify_and_route("What are your hours?", "tenant-a")

    mock_client.post.assert_called_once()
    _, kwargs = mock_client.post.call_args
    assert kwargs["json"] == {"text": "What are your hours?"}

    assert decision.action == "agent"
    assert decision.label == "faq_rag"
    assert decision.routed_to == "agent"


@pytest.mark.asyncio
async def test_lead_capture_routes_to_agent():
    with patch("app.services.router.httpx.AsyncClient") as mock_client_cls:
        mock_client = _setup_mock_client(mock_client_cls, "lead_capture", 0.92)
        decision = await classify_and_route("I'd like to sign up", "tenant-a")

    mock_client.post.assert_called_once()
    _, kwargs = mock_client.post.call_args
    assert kwargs["json"] == {"text": "I'd like to sign up"}

    assert decision.action == "agent"
    assert decision.label == "lead_capture"
    assert decision.routed_to == "agent"


@pytest.mark.asyncio
async def test_human_escalate_routes_to_agent():
    with patch("app.services.router.httpx.AsyncClient") as mock_client_cls:
        _setup_mock_client(mock_client_cls, "human_escalate", 0.90)
        decision = await classify_and_route("I need to speak to a human", "tenant-a")

    assert decision.action == "agent"
    assert decision.label == "human_escalate"
    assert decision.routed_to == "agent"


@pytest.mark.asyncio
async def test_spam_is_dropped():
    with patch("app.services.router.httpx.AsyncClient") as mock_client_cls:
        _setup_mock_client(mock_client_cls, "spam", 0.98)
        decision = await classify_and_route("BUY CHEAP MEDS NOW", "tenant-a")

    assert decision.action == "direct"
    assert decision.label == "spam"
    assert decision.reply is None


@pytest.mark.asyncio
async def test_other_agent_routes_to_agent():
    with patch("app.services.router.httpx.AsyncClient") as mock_client_cls:
        _setup_mock_client(mock_client_cls, "other_agent", 0.85)
        decision = await classify_and_route("Tell me about yourself", "tenant-a")

    assert decision.action == "agent"
    assert decision.label == "other_agent"
    assert decision.routed_to == "agent"


@pytest.mark.asyncio
async def test_low_confidence_falls_back_to_agent():
    with patch("app.services.router.httpx.AsyncClient") as mock_client_cls:
        _setup_mock_client(mock_client_cls, "faq_rag", 0.3)
        decision = await classify_and_route("hi there", "tenant-a")

    assert decision.action == "agent"
    assert decision.routed_to == "agent"


@pytest.mark.asyncio
async def test_http_error_falls_back_to_agent():
    with patch("app.services.router.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        decision = await classify_and_route("hello", "tenant-a")

    assert decision.action == "agent"
    assert decision.label == "unknown"


@pytest.mark.asyncio
async def test_ambiguous_label_falls_back_to_agent():
    with patch("app.services.router.httpx.AsyncClient") as mock_client_cls:
        _setup_mock_client(mock_client_cls, "ambiguous", 0.85)
        decision = await classify_and_route("what is the meaning of life?", "tenant-a")

    assert decision.action == "agent"
    assert decision.routed_to == "agent"


@pytest.mark.asyncio
async def test_request_body_uses_text_key():
    """Regression: classifier expects {"text": ...}, not {"message": ...}."""
    with patch("app.services.router.httpx.AsyncClient") as mock_client_cls:
        mock_client = _setup_mock_client(mock_client_cls, "faq_rag", 0.95)
        await classify_and_route("hello world", "tenant-b")

    _, kwargs = mock_client.post.call_args
    assert "text" in kwargs["json"]
    assert "message" not in kwargs["json"]
    assert kwargs["json"]["text"] == "hello world"
