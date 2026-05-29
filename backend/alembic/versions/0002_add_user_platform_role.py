"""add user platform_role

Revision ID: 0002_add_user_platform_role
Revises: 0001
Create Date: 2026-05-25

Adds a nullable platform-level role column to users (e.g. "tenant_manager").
This is platform-level and distinct from tenant_memberships.role.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_add_user_platform_role"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("platform_role", sa.String(), nullable=True))
    # The only legal platform role is tenant_manager (or NULL for tenant-scoped users).
    op.create_check_constraint(
        "ck_users_platform_role",
        "users",
        "platform_role IS NULL OR platform_role = 'tenant_manager'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_platform_role", "users", type_="check")
    op.drop_column("users", "platform_role")
