"""Enforce tenant-scoped memberships (tenant_id NOT NULL + tenant-only roles).

The platform ``tenant_manager`` is represented ONLY by ``users.platform_role``
and has no membership row, so ``tenant_memberships`` is strictly tenant-scoped:
``tenant_id`` is NOT NULL and ``role`` is one of the two tenant roles. This
migration enforces that invariant. (``tenant_id`` is already NOT NULL from 0001;
it is re-asserted here to make the intent explicit and the chain self-documenting.)

Revision ID: 0005_tenant_membership_scope
Revises: 0004_widget_tables
Create Date: 2026-05-29
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005_tenant_membership_scope"
down_revision: str | None = "0004_widget_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("tenant_memberships", "tenant_id", nullable=False)
    op.create_check_constraint(
        "ck_tenant_memberships_role",
        "tenant_memberships",
        "role IN ('tenant_admin', 'member')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tenant_memberships_role", "tenant_memberships", type_="check")
