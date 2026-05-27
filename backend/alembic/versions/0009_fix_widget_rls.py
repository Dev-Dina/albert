"""Fix widget table RLS policies — wrong session variable in 0004.

Revision ID: 0009_fix_widget_rls
Revises: 0008_cost_events_drop_rls
Create Date: 2026-05-27

Migration 0004 created RLS policies on the four widget tables using
``app.tenant_id`` as the session variable.  The application sets
``app.current_tenant`` (see backend/app/tenancy/rls.py, _RLS_VAR).
``app.tenant_id`` is never set, so the policies always evaluated to
``tenant_id = NULL`` — matching zero rows on every request and blocking
all INSERTs via the WITH CHECK clause.

This migration drops the broken policies and recreates them with:
  - correct variable: app.current_tenant
  - nullif guard: handles the empty-string quirk on pooled connections
  - true second argument: returns NULL instead of raising when unset
  - both USING and WITH CHECK clauses

Affected tables (all owned by Owner D / widget slice):
  widgets, widget_allowed_origins,
  widget_guardrail_configs, widget_signing_key_versions
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_fix_widget_rls"
down_revision: str | None = "0008_cost_events_drop_rls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "widgets",
    "widget_allowed_origins",
    "widget_guardrail_configs",
    "widget_signing_key_versions",
)

# Correct expression — matches what rls.py sets on every request.
_CORRECT_EXPR = (
    "tenant_id = nullif(current_setting('app.current_tenant', true), '')::uuid"
)

# Broken expression from 0004 — wrong variable, no nullif guard.
_BROKEN_EXPR = "tenant_id = current_setting('app.tenant_id', true)::uuid"


def upgrade() -> None:
    for table in _TABLES:
        old_policy = f"{table}_tenant_isolation"
        op.execute(f"DROP POLICY IF EXISTS {old_policy} ON {table}")
        op.execute(
            f"CREATE POLICY {old_policy} ON {table} "
            f"USING ({_CORRECT_EXPR}) "
            f"WITH CHECK ({_CORRECT_EXPR})"
        )


def downgrade() -> None:
    for table in _TABLES:
        policy = f"{table}_tenant_isolation"
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
        op.execute(
            f"CREATE POLICY {policy} ON {table} "
            f"USING ({_BROKEN_EXPR}) "
            f"WITH CHECK ({_BROKEN_EXPR})"
        )
