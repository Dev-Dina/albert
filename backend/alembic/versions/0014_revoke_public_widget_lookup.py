"""Revoke PUBLIC EXECUTE on lookup_widget_by_public_id; keep it for albert_app.

Completes the TODO documented in 0012_grant_widget_function: that migration
granted EXECUTE on the SECURITY DEFINER function ``lookup_widget_by_public_id``
to PUBLIC as a stopgap because no dedicated low-privilege application role
existed yet, with the explicit note:

    "When a dedicated low-privilege application role is created, update this
     migration to REVOKE FROM PUBLIC and GRANT to that role instead."

That role (``albert_app``) now exists (0013 grants it EXECUTE on all functions),
so PUBLIC no longer needs it. Narrowing EXECUTE to the application role is the
intended end state and the behaviour the isolation eval
``test_public_execute_on_widget_lookup_is_revoked`` asserts.

Revision ID: 0014_revoke_public_widget_lookup
Revises: 0013_grant_app_role
"""

from __future__ import annotations

from alembic import op

revision = "0014_revoke_public_widget_lookup"
down_revision = "0013_grant_app_role"
branch_labels = None
depends_on = None

_FUNC = "lookup_widget_by_public_id(text)"


def upgrade() -> None:
    # albert_app already has EXECUTE via 0013; re-assert it so the function stays
    # callable by the app role independent of grant ordering, then drop PUBLIC.
    op.execute(f"GRANT EXECUTE ON FUNCTION {_FUNC} TO albert_app")
    op.execute(f"REVOKE EXECUTE ON FUNCTION {_FUNC} FROM PUBLIC")


def downgrade() -> None:
    # Restore the 0012 state (PUBLIC may execute).
    op.execute(f"GRANT EXECUTE ON FUNCTION {_FUNC} TO PUBLIC")
