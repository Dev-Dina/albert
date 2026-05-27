"""Grant EXECUTE on lookup_widget_by_public_id to the connecting role.

Revision ID: 0011_grant_widget_function
Revises: 0010_fix_chunk_rls
Create Date: 2026-05-27

Migration 0004 created the SECURITY DEFINER function
``lookup_widget_by_public_id`` and then did:

    REVOKE ALL ON FUNCTION lookup_widget_by_public_id(text) FROM PUBLIC;

But it never issued a corresponding GRANT.  The intent (comment in 0004)
was "granted to the backend role only", but no backend role was created
and no GRANT was issued.

Current state: only a superuser (postgres) can call the function.
The application connects as postgres today, so it works — but it is
an undocumented dependency on superuser access.

This migration grants EXECUTE to the PUBLIC role.  The function itself
is the security boundary: SECURITY DEFINER, fixed search_path, returns
only (widget_id, tenant_id, status) — no sensitive content.  The
REVOKE FROM PUBLIC was overly restrictive given that there is no
separate application role.

When a dedicated low-privilege application role is created, update this
migration to REVOKE FROM PUBLIC and GRANT to that role instead.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011_grant_widget_function"
down_revision: str | None = "0010_fix_chunk_rls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FUNC = "lookup_widget_by_public_id(text)"


def upgrade() -> None:
    op.execute(f"GRANT EXECUTE ON FUNCTION {_FUNC} TO PUBLIC")


def downgrade() -> None:
    op.execute(f"REVOKE EXECUTE ON FUNCTION {_FUNC} FROM PUBLIC")
