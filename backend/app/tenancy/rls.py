"""Per-request tenant context management (Row-Level Security).

Rule: every request that touches a tenant-owned table MUST call
``set_tenant_context`` at the start of its transaction, and MUST call
``clear_tenant_context`` in a finally block before the session is returned
to the pool.

Why transaction-local (is_local=True)?
  set_config('app.current_tenant', tid, True) is equivalent to SET LOCAL:
  the value is scoped to the current transaction and reverts automatically
  on commit or rollback.  This prevents stale context leaking to the next
  request that reuses the same pooled connection.

The explicit clear_tenant_context call in the finally block is a second
safety net: if the transaction is somehow closed outside SQLAlchemy's normal
commit/rollback path, the explicit RESET removes any residual value before
the connection is handed back to the pool.
"""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# The Postgres session variable that every RLS policy reads.
TENANT_CONTEXT_GUC = "app.current_tenant"
_RLS_VAR = TENANT_CONTEXT_GUC


async def set_tenant_context(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Set the transaction-local RLS variable to ``tenant_id``.

    Must be called inside the same transaction as the request's queries.
    Uses is_local=true so the value is automatically cleared on commit/rollback.
    """
    await db.execute(
        text("SELECT set_config(:var, :tid, true)"),
        {"var": _RLS_VAR, "tid": str(tenant_id)},
    )


async def clear_tenant_context(db: AsyncSession) -> None:
    """Explicitly reset the RLS variable to empty string.

    Called in the finally block of the tenant_scope dependency.  Works as a
    belt-and-suspenders reset on top of the transaction-local (is_local=true)
    mechanism: even if the connection is somehow reused with a lingering
    session-level value, this clears it before the connection returns to the pool.
    """
    await db.execute(
        text("SELECT set_config(:var, '', true)"),
        {"var": _RLS_VAR},
    )


async def get_current_tenant_context(db: AsyncSession) -> str:
    """Return the raw value of app.current_tenant on this connection.

    Returns empty string when unset.  Used in isolation tests to verify the
    pooled-connection reset guarantee.
    """
    result = await db.execute(
        text("SELECT current_setting(:var, true)"),
        {"var": _RLS_VAR},
    )
    value = result.scalar()
    return value or ""
