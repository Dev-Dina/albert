from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.router import classify_and_route


def _mock_response(label: str, confidence: float) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {"label": label, "confidence": confidence}
    resp.raise_for_status = MagicMock()
    return resp


@pytest.mark.asyncio
async def test_greeting_returns_direct_reply():
    with patch("app.services.router.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=_mock_response("greeting", 0.95))
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        decision = await classify_and_route("hello", "tenant-a")

    assert decision.action == "direct"
    assert decision.routed_to == "router"
    assert "hello" in decision.reply.lower() or "help" in decision.reply.lower()


@pytest.mark.asyncio
async def test_farewell_returns_direct_reply():
    with patch("app.services.router.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=_mock_response("farewell", 0.92))
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        decision = await classify_and_route("goodbye", "tenant-a")

    assert decision.action == "direct"
    assert decision.routed_to == "router"
    assert "goodbye" in decision.reply.lower() or "thank" in decision.reply.lower()


@pytest.mark.asyncio
async def test_low_confidence_falls_back_to_agent():
    with patch("app.services.router.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=_mock_response("greeting", 0.3))
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

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
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=_mock_response("ambiguous", 0.85))
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        decision = await classify_and_route("what is the meaning of life?", "tenant-a")

    assert decision.action == "agent"
    assert decision.routed_to == "agent"
