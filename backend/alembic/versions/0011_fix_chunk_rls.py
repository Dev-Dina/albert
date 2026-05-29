"""Fix RAG chunk table RLS policies — missing guards in 0006.

Revision ID: 0011_fix_chunk_rls
Revises: 0010_fix_widget_rls
Create Date: 2026-05-27

Migration 0006 created RLS policies on parent_chunks and child_chunks with
two defects:

1. Missing ``true`` second argument to current_setting:
       current_setting('app.current_tenant')   -- WRONG
       current_setting('app.current_tenant', true)  -- correct
   Without ``true``, Postgres raises an error if the variable is not set
   instead of returning NULL.  Any request that touches these tables before
   tenant context is established (health checks, background tasks) would
   crash with a Postgres exception rather than returning zero rows.

2. Missing nullif guard:
       current_setting(...)::uuid               -- WRONG
       nullif(current_setting(..., true), '')::uuid  -- correct
   After clear_tenant_context sets the variable to empty string, casting
   '' to uuid raises ``invalid input syntax for type uuid``.  The nullif
   converts empty string to NULL before the cast, so the comparison safely
   returns no rows.

3. Missing WITH CHECK clause:
   Migration 0006 only provided USING, not WITH CHECK.  Postgres falls back
   to USING for write-check when WITH CHECK is absent, but this should be
   explicit so the intent is visible.

Affected tables (owned by Owner B / RAG slice):
  parent_chunks, child_chunks
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_fix_chunk_rls"
down_revision: str | None = "0010_fix_widget_rls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("parent_chunks", "child_chunks")

# Correct expression — matches 0003 standard and what rls.py sets.
_CORRECT_EXPR = (
    "tenant_id = nullif(current_setting('app.current_tenant', true), '')::uuid"
)

# Broken expression from 0006 — missing true arg and nullif guard.
_BROKEN_EXPR = "tenant_id = current_setting('app.current_tenant')::uuid"


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({_CORRECT_EXPR}) "
            f"WITH CHECK ({_CORRECT_EXPR})"
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({_BROKEN_EXPR})"
            # No WITH CHECK — matches the original 0006 state.
        )
