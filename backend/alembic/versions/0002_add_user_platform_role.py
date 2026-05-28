"""add user platform_role

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-25

Adds a nullable platform-level role column to users (e.g. "tenant_manager").
This is platform-level and distinct from tenant_memberships.role.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("platform_role", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "platform_role")
