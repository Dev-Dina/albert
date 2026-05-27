import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import FastAPI

from app.adapters.embedder import build_embedder_adapter
from app.adapters.llm import build_llm_adapter
from app.adapters.reranker import build_reranker_adapter
from app.core.config import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup: build singletons and attach to app.state.
    Shutdown: dispose them cleanly.
    """
    logger.info("lifespan.startup begin")

    app.state.llm = await build_llm_adapter()
    logger.info("lifespan.startup llm_adapter=ready")

    app.state.embedder = await build_embedder_adapter()
    logger.info("lifespan.startup embedder_adapter=ready")

    app.state.reranker = await build_reranker_adapter()
    logger.info("lifespan.startup reranker_adapter=ready")

    redis_url = settings.redis_url or "redis://localhost:6379"
    app.state.redis = aioredis.from_url(redis_url, decode_responses=True)
    logger.info("lifespan.startup redis=ready url=%s", redis_url)

    yield

    await app.state.redis.aclose()

    logger.info("lifespan.shutdown begin")
    logger.info("lifespan.shutdown complete")
