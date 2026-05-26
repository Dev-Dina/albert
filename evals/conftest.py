"""Shared pytest fixtures for the evals isolation test suite.

Provides:
  - Two fixed tenant UUIDs (tenant_a, tenant_b) for cross-tenant tests.
  - A tenant_manager user UUID.
  - An async SQLAlchemy session connected to the test database.

All tests in evals/isolation/ import from here via conftest discovery.

Run inside Docker (recommended — resolves the postgres hostname):

    docker compose exec backend uv run pytest evals/ -v

Or set DATABASE_URL to a host-reachable DB:

    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/albert \
        uv run pytest evals/ -v
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# pytest-asyncio >= 0.21 requires async fixtures to use @pytest_asyncio.fixture.

from app.core.config import settings

# ---------------------------------------------------------------------------
# Fixed UUIDs — stable across test runs so seed data can use ON CONFLICT
# ---------------------------------------------------------------------------

TENANT_A_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
TENANT_B_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")
MANAGER_USER_ID = uuid.UUID("ffffffff-0000-0000-0000-000000000001")

_DB_URL = settings.database_url or "postgresql+asyncpg://postgres:postgres@postgres:5432/albert"


# ---------------------------------------------------------------------------
# Engine — module-scoped so connection pool is shared across tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def event_loop():
    """Override the default function-scoped event loop with a module-scoped one."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def db_engine():
    engine = create_async_engine(_DB_URL, future=True, pool_size=2, max_overflow=0)
    yield engine
    asyncio.run(engine.dispose())


@pytest_asyncio.fixture
async def db(db_engine) -> AsyncSession:
    """Yield a fresh async session; always rolls back after the test."""
    SessionLocal = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Tenant / user fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tenant_a() -> uuid.UUID:
    return TENANT_A_ID


@pytest.fixture
def tenant_b() -> uuid.UUID:
    return TENANT_B_ID


@pytest.fixture
def manager_user_id() -> uuid.UUID:
    return MANAGER_USER_ID
