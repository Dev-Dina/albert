"""widget tables + RLS

Revision ID: 0004_widget_tables
Revises: 0003_tenant_owned_tables_rls
Create Date: 2026-05-26

Creates the tenant-scoped widget tables (widgets, widget_allowed_origins,
widget_guardrail_configs, widget_signing_key_versions) and their Row-Level
Security policies, plus a SECURITY DEFINER lookup function used by the
public token-exchange path to resolve a tenant_id from a public widget_id
*before* a tenant context exists.

The signing key MATERIAL lives in Vault, never in Postgres; this migration
only stores key metadata (version + activation flag).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_widget_tables"
down_revision: str | None = "0003_tenant_owned_tables_rls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TENANT_TABLES = (
    "widgets",
    "widget_allowed_origins",
    "widget_guardrail_configs",
    "widget_signing_key_versions",
)


def upgrade() -> None:
    op.create_table(
        "widgets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("public_widget_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column(
            "theme", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("greeting", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("status", sa.String(), nullable=False, server_default="enabled"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("public_widget_id", name="uq_widgets_public_widget_id"),
        sa.CheckConstraint(
            "status IN ('enabled', 'disabled')", name="ck_widgets_status",
        ),
        sa.CheckConstraint(
            "public_widget_id ~ '^[A-Za-z0-9]{22}$'",
            name="ck_widgets_public_widget_id_format",
        ),
        sa.CheckConstraint(
            "char_length(greeting) <= 500", name="ck_widgets_greeting_length",
        ),
    )
    op.create_index("ix_widgets_tenant_id", "widgets", ["tenant_id"])

    op.create_table(
        "widget_allowed_origins",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("tenant_id", "origin", name="uq_widget_allowed_origins_tenant_origin"),
        sa.CheckConstraint(
            "origin !~ '\\*'", name="ck_widget_allowed_origins_no_wildcard",
        ),
        sa.CheckConstraint(
            "origin NOT LIKE '%/%/%'",
            name="ck_widget_allowed_origins_no_path",
        ),
    )
    op.create_index(
        "ix_widget_allowed_origins_tenant_id", "widget_allowed_origins", ["tenant_id"]
    )

    op.create_table(
        "widget_guardrail_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("tenant_id", name="uq_widget_guardrail_configs_tenant"),
    )

    op.create_table(
        "widget_signing_key_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tenant_id", "version", name="uq_widget_signing_key_versions_tenant_version"
        ),
        sa.CheckConstraint("version >= 1", name="ck_widget_signing_key_versions_version_pos"),
    )
    op.create_index(
        "ix_widget_signing_key_versions_tenant_id",
        "widget_signing_key_versions",
        ["tenant_id"],
    )
    # Exactly one active row per tenant.
    op.create_index(
        "uq_widget_signing_key_versions_tenant_active",
        "widget_signing_key_versions",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    # Row-Level Security: every tenant table is gated on app.tenant_id.
    for table in _TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
              USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
              WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
            """
        )

    # SECURITY DEFINER lookup used by the token-exchange path. Returns the
    # minimum info needed to set tenant context (widget_id, tenant_id, status);
    # never any other column. Granted to the backend role only.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION lookup_widget_by_public_id(p_public_id text)
        RETURNS TABLE(widget_id uuid, tenant_id uuid, status text)
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = public
        AS $$
          SELECT id, tenant_id, status
          FROM widgets
          WHERE public_widget_id = p_public_id;
        $$;
        """
    )
    op.execute(
        "REVOKE ALL ON FUNCTION lookup_widget_by_public_id(text) FROM PUBLIC;"
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS lookup_widget_by_public_id(text);")
    for table in _TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table};")
    op.drop_index(
        "uq_widget_signing_key_versions_tenant_active",
        table_name="widget_signing_key_versions",
    )
    op.drop_index(
        "ix_widget_signing_key_versions_tenant_id", table_name="widget_signing_key_versions"
    )
    op.drop_table("widget_signing_key_versions")
    op.drop_table("widget_guardrail_configs")
    op.drop_index(
        "ix_widget_allowed_origins_tenant_id", table_name="widget_allowed_origins"
    )
    op.drop_table("widget_allowed_origins")
    op.drop_index("ix_widgets_tenant_id", table_name="widgets")
    op.drop_table("widgets")
