"""Grant table/sequence/function privileges to the albert_app application role.

The albert_app role is created by postgres/init/01_create_app_role.sql on
container first-start with NOSUPERUSER + NOBYPASSRLS so that PostgreSQL
enforces FORCE ROW LEVEL SECURITY on every query the app makes.

This migration grants access to all tables that already exist (0001–0012).
Tables created by future migrations get grants automatically via
ALTER DEFAULT PRIVILEGES set in the init SQL.

Revision ID: 0013_grant_app_role
Revises: 0012_grant_widget_function
"""

from __future__ import annotations

from alembic import op

revision = "0013_grant_app_role"
down_revision = "0012_grant_widget_function"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("GRANT USAGE ON SCHEMA public TO albert_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO albert_app"
    )
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO albert_app")
    op.execute("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO albert_app")


def downgrade() -> None:
    op.execute("REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM albert_app")
    op.execute(
        "REVOKE USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public FROM albert_app"
    )
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM albert_app"
    )
    op.execute("REVOKE USAGE ON SCHEMA public FROM albert_app")
