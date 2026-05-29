from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.tenancy.rls import TENANT_CONTEXT_GUC


async def get_tenant_db(tenant_id: str) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a session with app.current_tenant set.

    Sets the RLS session variable so every query in this session is
    automatically filtered to the correct tenant. Resets it on exit so
    pooled connections never carry a stale tenant context.
    """
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config(:var, :tid, true)"),
            {"var": TENANT_CONTEXT_GUC, "tid": tenant_id},
        )
        try:
            yield session
        finally:
            await session.execute(
                text("SELECT set_config(:var, '', true)"),
                {"var": TENANT_CONTEXT_GUC},
            )
