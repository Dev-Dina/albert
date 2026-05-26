import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from app.adapters.llm import build_llm_adapter

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup: build singletons and attach to app.state.
    Shutdown: dispose them cleanly.
    """
    logger.info("lifespan.startup begin")

    app.state.llm = await build_llm_adapter()
    logger.info("lifespan.startup llm_adapter=ready")

    yield

    logger.info("lifespan.shutdown begin")
    # Nothing to dispose on the Groq client for now.
    # Add async close calls here as more singletons are added (httpx, db engine, redis).
    logger.info("lifespan.shutdown complete")
