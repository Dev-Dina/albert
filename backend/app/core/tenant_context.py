"""Per-request tenant context.

Sets the PostgreSQL session-local variable ``app.tenant_id`` so RLS policies
on tenant-scoped tables resolve to exactly the calling tenant's rows. A
request without a tenant context set will see zero rows from tenant-scoped
tables (RLS policies ENABLE + FORCE), which is the intended fail-closed
behavior.

If Owner A's platform helper lands at the same location, this module
re-exports it instead of providing its own implementation.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@asynccontextmanager
async def tenant_context(session: AsyncSession, tenant_id: uuid.UUID) -> AsyncIterator[None]:
    """Set ``app.tenant_id`` for the surrounding block.

    Uses ``set_config(..., true)`` so the variable is bound to the current
    transaction and is automatically cleared when the transaction ends.
    SQLAlchemy autobegins a transaction on first execute, so callers do not
    need to open one explicitly.
    """
    if not isinstance(tenant_id, uuid.UUID):
        raise TypeError("tenant_id must be a uuid.UUID")
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)").bindparams(
            tid=str(tenant_id)
        )
    )
    try:
        yield
    finally:
        # Clear explicitly in case the caller continues to use the same
        # transaction for non-tenant work after exit. ``set_config(..., true)``
        # with an empty value resets the GUC for this transaction.
        await session.execute(
            text("SELECT set_config('app.tenant_id', '', true)")
        )
