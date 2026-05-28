"""chunk tables: parent_chunks and child_chunks with RLS and HNSW index

Revision ID: 0006_chunk_tables
Revises: 0005_nullable_tenant_id
Create Date: 2026-05-26

Creates parent_chunks and child_chunks tables for the RAG pipeline.
- Both tables carry tenant_id and are protected by RLS policies.
- child_chunks.embedding is vector(768) for Gemini text-embedding-004.
- HNSW index on child_chunks.embedding filtered by tenant_id for fast ANN search.
- Enables pgvector extension if not already present.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_chunk_tables"
down_revision: str | None = "0005_nullable_tenant_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_POLICY_USING = "tenant_id = nullif(current_setting('app.current_tenant', true), '')::uuid"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "parent_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_parent_chunks_tenant_id", "parent_chunks", ["tenant_id"])
    op.create_index("ix_parent_chunks_content_id", "parent_chunks", ["content_id"])

    op.create_table(
        "child_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("parent_chunks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=True),  # placeholder column type; vector cast below
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # Re-create embedding column as proper vector(768) after table exists.
    op.execute("ALTER TABLE child_chunks DROP COLUMN embedding")
    op.execute("ALTER TABLE child_chunks ADD COLUMN embedding vector(768)")

    op.create_index("ix_child_chunks_tenant_id", "child_chunks", ["tenant_id"])
    op.create_index("ix_child_chunks_parent_id", "child_chunks", ["parent_id"])

    # HNSW index for approximate nearest-neighbour search filtered by tenant_id.
    op.execute(
        "CREATE INDEX ix_child_chunks_embedding_hnsw "
        "ON child_chunks USING hnsw (embedding vector_cosine_ops)"
    )

    # RLS policies — tenant_id must match the session variable app.current_tenant.
    op.execute("ALTER TABLE parent_chunks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE parent_chunks FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE child_chunks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE child_chunks FORCE ROW LEVEL SECURITY")

    op.execute(
        "CREATE POLICY tenant_isolation ON parent_chunks "
        f"USING ({_POLICY_USING}) "
        f"WITH CHECK ({_POLICY_USING})"
    )
    op.execute(
        "CREATE POLICY tenant_isolation ON child_chunks "
        f"USING ({_POLICY_USING}) "
        f"WITH CHECK ({_POLICY_USING})"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE child_chunks NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE parent_chunks NO FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON child_chunks")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON parent_chunks")
    op.execute("DROP INDEX IF EXISTS ix_child_chunks_embedding_hnsw")
    op.drop_index("ix_child_chunks_parent_id", table_name="child_chunks")
    op.drop_index("ix_child_chunks_tenant_id", table_name="child_chunks")
    op.drop_table("child_chunks")
    op.drop_index("ix_parent_chunks_content_id", table_name="parent_chunks")
    op.drop_index("ix_parent_chunks_tenant_id", table_name="parent_chunks")
    op.drop_table("parent_chunks")
