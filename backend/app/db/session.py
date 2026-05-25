from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# Used only when DATABASE_URL is unset (e.g. local tests); engine creation is lazy and
# does not connect, so this never reaches a real database on import.
_DEFAULT_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@postgres:5432/albert"

async_engine = create_async_engine(
    settings.database_url or _DEFAULT_DATABASE_URL,
    future=True,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session."""
    async with AsyncSessionLocal() as session:
        yield session


async def check_database_health() -> dict:
    """Return database reachability. Never raises — safe for status checks."""
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        return {"reachable": False}
    return {"reachable": True}
