"""Remove RLS from cost_events — platform-readable billing table.

Revision ID: 0009_cost_events_drop_rls
Revises: 0008_fix_origin_check_constraint
Create Date: 2026-05-27

cost_events contains numeric billing data only (tokens, cost_usd).
It is queried by tenant_manager routes that do NOT go through tenant_scope,
so app.current_tenant is empty on those sessions.  With FORCE RLS active
the query silently returns zero rows for every tenant.

cost_events is not tenant content — it has no conversations, messages, or PII.
Access is controlled at the route layer (TenantManagerDep).  RLS is redundant
and actively harmful here.

Platform-owned tables without RLS: tenants, users, tenant_memberships,
audit_logs, cost_events (after this migration).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_cost_events_drop_rls"
down_revision: str | None = "0008_fix_origin_check_constraint"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "cost_events"
_POLICY = "cost_events_tenant_isolation"
_POLICY_EXPR = (
    "tenant_id = nullif(current_setting('app.current_tenant', true), '')::uuid"
)


def upgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {_POLICY} ON {_TABLE}")
    op.execute(f"ALTER TABLE {_TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {_POLICY} ON {_TABLE} "
        f"USING ({_POLICY_EXPR}) "
        f"WITH CHECK ({_POLICY_EXPR})"
    )
