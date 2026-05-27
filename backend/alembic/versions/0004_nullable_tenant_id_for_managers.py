"""Make tenant_memberships.tenant_id nullable for platform-level manager rows.

Platform managers (role=tenant_manager) are not scoped to any tenant, so their
membership row has tenant_id=NULL.  The existing NOT NULL constraint blocks this.

Changes:
- DROP NOT NULL on tenant_memberships.tenant_id
- Add a partial unique index to prevent duplicate platform memberships per user

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("tenant_memberships", "tenant_id", nullable=True)
    op.execute(
        "CREATE UNIQUE INDEX uq_mgr_membership ON tenant_memberships (user_id) "
        "WHERE tenant_id IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_mgr_membership")
    op.alter_column("tenant_memberships", "tenant_id", nullable=False)
