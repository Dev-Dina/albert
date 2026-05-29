"""initial platform tables

Revision ID: 0001
Revises:
Create Date: 2026-05-25

Creates the platform-owned tables (tenants, users, tenant_memberships, audit_logs).
UUID primary keys are application-generated (uuid4), so no DB extension is required.
No tenant-owned tables and no RLS policies are created in this migration.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "tenant_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_tenant_memberships_tenant_user"),
    )
    op.create_index("ix_tenant_memberships_tenant_id", "tenant_memberships", ["tenant_id"])
    op.create_index("ix_tenant_memberships_user_id", "tenant_memberships", ["user_id"])
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "target_tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # ------------------------------------------------------------------
    # Dedicated NON-SUPERUSER runtime application role (RLS-enforced).
    #
    # The runtime backend MUST connect as this role (DATABASE_URL) so FORCE ROW
    # LEVEL SECURITY is actually enforced — a superuser / BYPASSRLS login
    # silently bypasses every tenant policy. Migrations/admin keep using the
    # superuser login (MIGRATION_DATABASE_URL). The role is NOT a table owner and
    # is NOT BYPASSRLS, so RLS applies to it without exception.
    #
    # Default privileges below auto-grant DML on tables created by *later*
    # migrations (0003/0004/0006/...), so no per-migration grant bookkeeping is
    # needed. The dev password is a local placeholder (mirrors postgres:postgres);
    # rotate it and source from a secret store outside local dev.
    # ------------------------------------------------------------------
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'albert_app') THEN
                CREATE ROLE albert_app LOGIN PASSWORD 'albert_app'
                    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
            END IF;
        END
        $$;
        """
    )
    op.execute(
        "DO $$ BEGIN "
        "EXECUTE format('GRANT CONNECT ON DATABASE %I TO albert_app', current_database()); "
        "END $$;"
    )
    op.execute("GRANT USAGE ON SCHEMA public TO albert_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO albert_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO albert_app")
    # Future tables/sequences created by the migration role auto-grant to albert_app.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO albert_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT USAGE, SELECT ON SEQUENCES TO albert_app"
    )


def downgrade() -> None:
    # Revoke privileges before dropping the role (DROP ROLE fails while the role
    # still holds grants or default-privilege entries).
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM albert_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE USAGE, SELECT ON SEQUENCES FROM albert_app"
    )
    op.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM albert_app")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM albert_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM albert_app")
    op.execute(
        "DO $$ BEGIN "
        "EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM albert_app', current_database()); "
        "END $$;"
    )
    op.execute("DROP ROLE IF EXISTS albert_app")

    op.drop_table("audit_logs")
    op.drop_index("ix_tenant_memberships_user_id", table_name="tenant_memberships")
    op.drop_index("ix_tenant_memberships_tenant_id", table_name="tenant_memberships")
    op.drop_table("tenant_memberships")
    op.drop_table("users")
    op.drop_table("tenants")
