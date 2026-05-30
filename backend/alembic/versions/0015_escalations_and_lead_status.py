"""escalations table (RLS) + leads.status_changed_at

Adds the tenant-owned ``escalations`` table that captures the reason/summary of a
human-handoff for a conversation (1:1 per conversation), and a
``leads.status_changed_at`` column used by the lead lifecycle state machine.

The ``escalations`` table follows the same tenant-isolation contract as the
tables in 0003: it is created with FORCE ROW LEVEL SECURITY and a policy keyed on
the per-request session variable ``app.current_tenant`` (set via
``SELECT set_config('app.current_tenant', :tid, true)``). Empty/unset GUC →
``nullif`` guard yields NULL → no rows matched (fail closed).

Privileges: the ``escalations`` table inherits SELECT/INSERT/UPDATE/DELETE grants
to ``albert_app`` automatically via the ALTER DEFAULT PRIVILEGES configured in the
init SQL (see 0013_grant_app_role) — the same way 0003's tables did.

Revision ID: 0015_escalations_and_lead_status
Revises: 0014_revoke_public_widget_lookup
Create Date: 2026-05-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_escalations_and_lead_status"
down_revision: str | None = "0014_revoke_public_widget_lookup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Same fail-closed policy expression used across tenant-owned tables (0003).
_POLICY_USING = (
    "tenant_id = nullif(current_setting('app.current_tenant', true), '')::uuid"
)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # escalations — captured human-handoff context, 1:1 per conversation
    # ------------------------------------------------------------------
    op.create_table(
        "escalations",
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
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
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
        # 1:1 — at most one escalation record per conversation (FR-034).
        sa.UniqueConstraint("conversation_id", name="uq_escalations_conversation"),
    )
    op.create_index("ix_escalations_tenant_id", "escalations", ["tenant_id"])

    # Enable + force RLS with the tenant-isolation policy (mirrors 0003).
    op.execute("ALTER TABLE escalations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE escalations FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY escalations_tenant_isolation
        ON escalations
        USING ({_POLICY_USING})
        WITH CHECK ({_POLICY_USING})
        """
    )

    # ------------------------------------------------------------------
    # leads.status_changed_at — set on each lifecycle transition
    # ------------------------------------------------------------------
    op.add_column(
        "leads",
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("leads", "status_changed_at")

    op.execute("DROP POLICY IF EXISTS escalations_tenant_isolation ON escalations")
    op.execute("ALTER TABLE escalations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE escalations DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_escalations_tenant_id", table_name="escalations")
    op.drop_table("escalations")
