"""escalations.status + resolved_at/resolved_by (resolve/reopen lifecycle)

Adds a two-state lifecycle to the tenant-owned ``escalations`` table so a
tenant-admin can mark an escalated conversation handled (``resolved``) or send it
back to the working list (``open``), with a light audit trail of who resolved it
and when.

This migration is **additive only**: it adds three columns and makes **no change
to row-level security**. The ``escalations`` table already has FORCE ROW LEVEL
SECURITY and the ``escalations_tenant_isolation`` policy keyed on
``app.current_tenant`` (migration 0015). The new columns are unrelated to
``tenant_id`` and therefore cannot weaken or alter that policy — so no policy,
ENABLE, or FORCE statement is touched here.

Columns:
- ``status``      text NOT NULL, server_default ``'open'`` (back-fills existing
  rows to ``open``). Valid values ``open`` / ``resolved`` are enforced in the app
  layer (Pydantic enum + ``escalation_lifecycle``), mirroring the lead-status
  approach — no DB CHECK constraint (see specs/008-resolve-escalation/research.md D3).
- ``resolved_at`` timestamptz NULL — set on resolve, cleared on reopen.
- ``resolved_by`` uuid NULL — the acting admin's ``user_id`` (light audit trail).
  Intentionally **not** a foreign key (see research.md D1).

Revision ID: 0016_escalation_status
Revises: 0015_escalations_and_lead_status
Create Date: 2026-05-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_escalation_status"
down_revision: str | None = "0015_escalations_and_lead_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "escalations",
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="open",
        ),
    )
    op.add_column(
        "escalations",
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "escalations",
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("escalations", "resolved_by")
    op.drop_column("escalations", "resolved_at")
    op.drop_column("escalations", "status")
