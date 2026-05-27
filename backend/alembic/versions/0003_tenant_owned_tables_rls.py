"""tenant-owned tables with RLS

Revision ID: 0003_tenant_owned_tables_rls
Revises: 0002_add_user_platform_role
Create Date: 2026-05-25

Creates every tenant-owned table, enables and forces RLS on each, and installs
a tenant-isolation policy keyed on the per-request session variable
``app.current_tenant``.

Session-variable rules (enforced at app layer, verified here):
- Set via: SELECT set_config('app.current_tenant', :tid, true)   -- is_local=true
- Unset/empty → nullif guard yields NULL → no rows matched (fail closed)
- FORCE ROW LEVEL SECURITY ensures the policy applies even to the table owner.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_tenant_owned_tables_rls"
down_revision: str | None = "0002_add_user_platform_role"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables that require tenant isolation.  Order matters for FK constraints.
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

# RLS policy template per table.
# nullif(current_setting('app.current_tenant', true), '') handles both NULL
# and empty-string cases that arise on pooled connections (real Postgres quirk).
_POLICY_USING = (
    "tenant_id = nullif(current_setting('app.current_tenant', true), '')::uuid"
)


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation
        ON {table}
        USING ({_POLICY_USING})
        WITH CHECK ({_POLICY_USING})
        """
    )


def _disable_rls(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def upgrade() -> None:
    # ------------------------------------------------------------------
    # cms_pages — tenant CMS content pages
    # ------------------------------------------------------------------
    op.create_table(
        "cms_pages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.UniqueConstraint("tenant_id", "slug", name="uq_cms_pages_tenant_slug"),
    )
    op.create_index("ix_cms_pages_tenant_id", "cms_pages", ["tenant_id"])

    # ------------------------------------------------------------------
    # content_chunks — pgvector embeddings for RAG, always tenant-filtered
    # ------------------------------------------------------------------
    op.create_table(
        "content_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "cms_page_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("cms_pages.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        # embedding stored as a JSON array until pgvector extension is wired;
        # replace with Vector(1536) once pgvector is confirmed available.
        sa.Column("embedding", postgresql.JSONB(), nullable=True),
        sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_content_chunks_tenant_id", "content_chunks", ["tenant_id"])

    # ------------------------------------------------------------------
    # conversations — chat sessions per visitor/tenant
    # ------------------------------------------------------------------
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
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
    )
    op.create_index("ix_conversations_tenant_id", "conversations", ["tenant_id"])

    # ------------------------------------------------------------------
    # messages — individual turns within a conversation
    # ------------------------------------------------------------------
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(), nullable=False),  # "user" | "assistant"
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_messages_tenant_id", "messages", ["tenant_id"])
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])

    # ------------------------------------------------------------------
    # leads — captured visitor leads
    # ------------------------------------------------------------------
    op.create_table(
        "leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("contact", sa.String(), nullable=False),
        sa.Column("intent", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="new"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_leads_tenant_id", "leads", ["tenant_id"])

    # ------------------------------------------------------------------
    # widget_configs — per-tenant widget appearance + behaviour
    # ------------------------------------------------------------------
    op.create_table(
        "widget_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        # Public widget identifier (not secret; the signed token is the boundary).
        sa.Column("public_widget_id", sa.String(), nullable=False, unique=True),
        # JSON array of allowed origin strings validated server-side on every request.
        sa.Column(
            "allowed_origins",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("persona_name", sa.String(), nullable=True),
        sa.Column(
            "config",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
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
    )
    op.create_index("ix_widget_configs_tenant_id", "widget_configs", ["tenant_id"])

    # ------------------------------------------------------------------
    # tenant_guardrail_configs — tenant-configurable rails (NOT platform rails)
    # ------------------------------------------------------------------
    op.create_table(
        "tenant_guardrail_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "allowed_topics",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "blocked_topics",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("refusal_tone", sa.String(), nullable=True),
        # enabled_tools is a subset of ["rag_search","capture_lead","escalate"]
        sa.Column(
            "enabled_tools",
            postgresql.JSONB(),
            nullable=False,
            server_default='["rag_search","capture_lead","escalate"]',
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_tenant_guardrail_configs_tenant_id",
        "tenant_guardrail_configs",
        ["tenant_id"],
    )

    # ------------------------------------------------------------------
    # cost_events — per-call token/$ attribution for billing
    # ------------------------------------------------------------------
    op.create_table(
        "cost_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("call_type", sa.String(), nullable=False),  # "llm" | "embedding"
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=6), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_cost_events_tenant_id", "cost_events", ["tenant_id"])
    op.create_index("ix_cost_events_created_at", "cost_events", ["created_at"])

    # ------------------------------------------------------------------
    # Enable + force RLS on every tenant-owned table
    # ------------------------------------------------------------------
    for table in _TENANT_OWNED_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in reversed(_TENANT_OWNED_TABLES):
        _disable_rls(table)

    op.drop_index("ix_cost_events_created_at", table_name="cost_events")
    op.drop_index("ix_cost_events_tenant_id", table_name="cost_events")
    op.drop_table("cost_events")

    op.drop_index(
        "ix_tenant_guardrail_configs_tenant_id",
        table_name="tenant_guardrail_configs",
    )
    op.drop_table("tenant_guardrail_configs")

    op.drop_index("ix_widget_configs_tenant_id", table_name="widget_configs")
    op.drop_table("widget_configs")

    op.drop_index("ix_leads_tenant_id", table_name="leads")
    op.drop_table("leads")

    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_index("ix_messages_tenant_id", table_name="messages")
    op.drop_table("messages")

    op.drop_index("ix_conversations_tenant_id", table_name="conversations")
    op.drop_table("conversations")

    op.drop_index("ix_content_chunks_tenant_id", table_name="content_chunks")
    op.drop_table("content_chunks")

    op.drop_index("ix_cms_pages_tenant_id", table_name="cms_pages")
    op.drop_table("cms_pages")
