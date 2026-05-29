"""baseline schema (fastapi-users users + full tenant isolation)

Revision ID: 0001
Revises:
Create Date: 2026-05-29

Single clean baseline (squash of the former 0001–0008). Creates:
  * Platform tables: tenants, users (fastapi-users-compatible: is_superuser/
    is_verified + platform_role with a CHECK), tenant_memberships (strictly
    tenant-scoped: tenant_id NOT NULL, role CHECK in tenant roles), audit_logs.
  * The non-superuser runtime role ``albert_app`` (NOBYPASSRLS) + grants.
  * pgvector extension.
  * All tenant-owned tables + widget tables + RAG chunk tables, each under
    ENABLE + FORCE ROW LEVEL SECURITY with a tenant-isolation policy keyed on
    the ``app.current_tenant`` GUC.
  * The SECURITY DEFINER ``lookup_widget_by_public_id`` function (token exchange).

Migrations run as the owner/superuser (MIGRATION_DATABASE_URL); the runtime app
connects as ``albert_app`` so FORCE RLS is actually enforced.
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

_POLICY_EXPR = "tenant_id = nullif(current_setting('app.current_tenant', true), '')::uuid"

# Tenant-owned tables (policy name: {table}_tenant_isolation).
_TENANT_OWNED_TABLES = [
    "cms_pages",
    "content_chunks",
    "conversations",
    "messages",
    "leads",
    "widget_configs",
    "tenant_guardrail_configs",
    "cost_events",
]
# Widget tables (policy name: {table}_tenant_isolation).
_WIDGET_TABLES = [
    "widgets",
    "widget_allowed_origins",
    "widget_guardrail_configs",
    "widget_signing_key_versions",
]
# RAG chunk tables (policy name: tenant_isolation).
_CHUNK_TABLES = ["parent_chunks", "child_chunks"]


def _isolation_policy(table: str, name: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {name} ON {table} "
        f"USING ({_POLICY_EXPR}) WITH CHECK ({_POLICY_EXPR})"
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ==================================================================
    # Platform tables (no RLS)
    # ==================================================================
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

    # fastapi-users-compatible users table. is_superuser/is_verified exist for
    # fastapi-users only; authorization uses platform_role + tenant_memberships.role.
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=1024), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("platform_role", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "platform_role IS NULL OR platform_role = 'tenant_manager'",
            name="ck_users_platform_role",
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # Strictly tenant-scoped membership: tenant_id NOT NULL, tenant roles only.
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
        sa.CheckConstraint(
            "role IN ('tenant_admin', 'member')", name="ck_tenant_memberships_role"
        ),
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

    # ==================================================================
    # Tenant-owned tables (RLS)
    # ==================================================================
    op.create_table(
        "cms_pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_cms_pages_tenant_slug"),
    )
    op.create_index("ix_cms_pages_tenant_id", "cms_pages", ["tenant_id"])

    # content_chunks: embedding is pgvector(1536) (squash of 0003 + 0007).
    op.create_table(
        "content_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cms_page_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cms_pages.id", ondelete="CASCADE"), nullable=True),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.execute("ALTER TABLE content_chunks ADD COLUMN embedding vector(1536)")
    op.create_index("ix_content_chunks_tenant_id", "content_chunks", ["tenant_id"])
    op.execute(
        "CREATE INDEX ix_content_chunks_embedding "
        "ON content_chunks USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_conversations_tenant_id", "conversations", ["tenant_id"])

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_messages_tenant_id", "messages", ["tenant_id"])
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])

    op.create_table(
        "leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("contact", sa.String(), nullable=False),
        sa.Column("intent", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="new"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_leads_tenant_id", "leads", ["tenant_id"])

    op.create_table(
        "widget_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("public_widget_id", sa.String(), nullable=False, unique=True),
        sa.Column("allowed_origins", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("persona_name", sa.String(), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_widget_configs_tenant_id", "widget_configs", ["tenant_id"])

    op.create_table(
        "tenant_guardrail_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("allowed_topics", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("blocked_topics", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("refusal_tone", sa.String(), nullable=True),
        sa.Column("enabled_tools", postgresql.JSONB(), nullable=False, server_default='["rag_search","capture_lead","escalate"]'),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_tenant_guardrail_configs_tenant_id", "tenant_guardrail_configs", ["tenant_id"])

    op.create_table(
        "cost_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("call_type", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=6), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_cost_events_tenant_id", "cost_events", ["tenant_id"])
    op.create_index("ix_cost_events_created_at", "cost_events", ["created_at"])

    # ==================================================================
    # Widget tables (RLS)
    # ==================================================================
    op.create_table(
        "widgets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("public_widget_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("theme", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("greeting", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("status", sa.String(), nullable=False, server_default="enabled"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("public_widget_id", name="uq_widgets_public_widget_id"),
        sa.CheckConstraint("status IN ('enabled', 'disabled')", name="ck_widgets_status"),
        sa.CheckConstraint("public_widget_id ~ '^[A-Za-z0-9]{22}$'", name="ck_widgets_public_widget_id_format"),
        sa.CheckConstraint("char_length(greeting) <= 500", name="ck_widgets_greeting_length"),
    )
    op.create_index("ix_widgets_tenant_id", "widgets", ["tenant_id"])

    op.create_table(
        "widget_allowed_origins",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("tenant_id", "origin", name="uq_widget_allowed_origins_tenant_origin"),
        sa.CheckConstraint("origin !~ '\\*'", name="ck_widget_allowed_origins_no_wildcard"),
        # Fixed shape check (was the broken NOT LIKE '%/%/%' in the old 0004).
        sa.CheckConstraint("origin ~ '^https?://[^/?# ]+$'", name="ck_widget_allowed_origins_shape"),
    )
    op.create_index("ix_widget_allowed_origins_tenant_id", "widget_allowed_origins", ["tenant_id"])

    op.create_table(
        "widget_guardrail_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.UniqueConstraint("tenant_id", name="uq_widget_guardrail_configs_tenant"),
    )

    op.create_table(
        "widget_signing_key_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "version", name="uq_widget_signing_key_versions_tenant_version"),
        sa.CheckConstraint("version >= 1", name="ck_widget_signing_key_versions_version_pos"),
    )
    op.create_index("ix_widget_signing_key_versions_tenant_id", "widget_signing_key_versions", ["tenant_id"])
    op.create_index(
        "uq_widget_signing_key_versions_tenant_active",
        "widget_signing_key_versions",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    # ==================================================================
    # RAG chunk tables (RLS)
    # ==================================================================
    op.create_table(
        "parent_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_parent_chunks_tenant_id", "parent_chunks", ["tenant_id"])
    op.create_index("ix_parent_chunks_content_id", "parent_chunks", ["content_id"])

    op.create_table(
        "child_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("parent_chunks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.execute("ALTER TABLE child_chunks ADD COLUMN embedding vector(768)")
    op.create_index("ix_child_chunks_tenant_id", "child_chunks", ["tenant_id"])
    op.create_index("ix_child_chunks_parent_id", "child_chunks", ["parent_id"])
    op.execute(
        "CREATE INDEX ix_child_chunks_embedding_hnsw "
        "ON child_chunks USING hnsw (embedding vector_cosine_ops)"
    )

    # ==================================================================
    # Row-Level Security policies
    # ==================================================================
    for table in _TENANT_OWNED_TABLES:
        _isolation_policy(table, f"{table}_tenant_isolation")
    for table in _WIDGET_TABLES:
        _isolation_policy(table, f"{table}_tenant_isolation")
    for table in _CHUNK_TABLES:
        _isolation_policy(table, "tenant_isolation")

    # ==================================================================
    # SECURITY DEFINER lookup for the widget token-exchange path (pre-context).
    # ==================================================================
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
    op.execute("REVOKE ALL ON FUNCTION lookup_widget_by_public_id(text) FROM PUBLIC;")

    # ==================================================================
    # Non-superuser runtime role + grants (created after all tables exist).
    # ==================================================================
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
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO albert_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "GRANT USAGE, SELECT ON SEQUENCES TO albert_app"
    )
    # albert_app invokes the SECURITY DEFINER lookup during token exchange,
    # before any tenant context exists. Least privilege: only this function.
    op.execute("GRANT EXECUTE ON FUNCTION lookup_widget_by_public_id(text) TO albert_app;")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS lookup_widget_by_public_id(text);")

    for table in _CHUNK_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    for table in _WIDGET_TABLES + _TENANT_OWNED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")

    op.execute("DROP INDEX IF EXISTS ix_child_chunks_embedding_hnsw")
    op.drop_table("child_chunks")
    op.drop_table("parent_chunks")

    op.drop_table("widget_signing_key_versions")
    op.drop_table("widget_guardrail_configs")
    op.drop_table("widget_allowed_origins")
    op.drop_table("widgets")

    op.drop_table("cost_events")
    op.drop_table("tenant_guardrail_configs")
    op.drop_table("widget_configs")
    op.drop_table("leads")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.execute("DROP INDEX IF EXISTS ix_content_chunks_embedding")
    op.drop_table("content_chunks")
    op.drop_table("cms_pages")

    op.drop_table("audit_logs")
    op.drop_table("tenant_memberships")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.drop_table("tenants")

    # Revoke + drop the runtime role last (after its grants are gone with the tables).
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM albert_app"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        "REVOKE USAGE, SELECT ON SEQUENCES FROM albert_app"
    )
    op.execute("REVOKE USAGE ON SCHEMA public FROM albert_app")
    op.execute(
        "DO $$ BEGIN "
        "EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM albert_app', current_database()); "
        "END $$;"
    )
    op.execute("DROP ROLE IF EXISTS albert_app")
