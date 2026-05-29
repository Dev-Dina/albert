"""Per-request tenant context — thin shim over app.tenancy.rls.

Sets the PostgreSQL session-local variable ``app.current_tenant`` so RLS policies
on tenant-scoped tables resolve to exactly the calling tenant's rows. A
request without a tenant context set will see zero rows from tenant-scoped
tables (RLS policies ENABLE + FORCE), which is the intended fail-closed
behavior.

The variable set is ``app.current_tenant`` (matching all RLS policies).
The previous implementation incorrectly used ``app.tenant_id``.
"""

from app.tenancy.rls import clear_tenant_context, set_tenant_context

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.tenancy.rls import TENANT_CONTEXT_GUC


@asynccontextmanager
async def tenant_context(session: AsyncSession, tenant_id: uuid.UUID) -> AsyncIterator[None]:
    """Set ``app.current_tenant`` for the surrounding block.

    Uses ``set_config(..., true)`` so the variable is bound to the current
    transaction and is automatically cleared when the transaction ends.
    SQLAlchemy autobegins a transaction on first execute, so callers do not
    need to open one explicitly.
    """
    if not isinstance(tenant_id, uuid.UUID):
        raise TypeError("tenant_id must be a uuid.UUID")
    await session.execute(
        text("SELECT set_config(:var, :tid, true)"),
        {"var": TENANT_CONTEXT_GUC, "tid": str(tenant_id)},
    )
    try:
        yield
    finally:
        # Clear explicitly in case the caller continues to use the same
        # transaction for non-tenant work after exit. ``set_config(..., true)``
        # with an empty value resets the GUC for this transaction.
        await session.execute(
            text("SELECT set_config(:var, '', true)"),
            {"var": TENANT_CONTEXT_GUC},
        )
