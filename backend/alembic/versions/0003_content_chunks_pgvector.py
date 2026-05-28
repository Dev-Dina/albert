"""content_chunks: replace JSONB embedding with pgvector Vector(1536)

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-26

Replaces the placeholder JSONB embedding column with a proper
pgvector vector(1536) column and adds an HNSW index for fast
approximate nearest-neighbour (ANN) retrieval.

Prerequisites:
  - The pgvector extension must be enabled:
      CREATE EXTENSION IF NOT EXISTS vector;
  - This is confirmed enabled in docker-compose.yml via the pgvector
    image (ankane/pgvector or pgvector/pgvector).

Index choice:
  - HNSW (hierarchical navigable small world) is preferred over IVFFlat
    for this workload: no training phase, better recall at low ef values,
    and safe to build on an empty table before any rows are inserted.
  - vector_cosine_ops matches the cosine similarity used in RAG retrieval.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ensure the pgvector extension is available.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Drop the placeholder JSONB column.
    op.drop_column("content_chunks", "embedding")

    # Add the proper vector column.
    op.execute("ALTER TABLE content_chunks ADD COLUMN embedding vector(1536)")

    # HNSW index for cosine-similarity ANN search, filtered by tenant via RLS.
    # Built after the column is added (table is empty on first migration run).
    op.execute(
        "CREATE INDEX ix_content_chunks_embedding "
        "ON content_chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_content_chunks_embedding")
    op.execute("ALTER TABLE content_chunks DROP COLUMN IF EXISTS embedding")
    op.add_column(
        "content_chunks",
        sa.Column("embedding", postgresql.JSONB(), nullable=True),
    )
