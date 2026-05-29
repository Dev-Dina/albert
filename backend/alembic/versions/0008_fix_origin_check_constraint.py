"""Fix widget_allowed_origins shape check (regex-based).

Revision ID: 0008_fix_origin_check_constraint
Revises: 0007_content_chunks_pgvector
Create Date: 2026-05-28

The original ``ck_widget_allowed_origins_no_path`` in revision 0004 used
``origin NOT LIKE '%/%/%'`` to reject paths. The ``%`` wildcard matches
empty strings, so the pattern actually matches every ``scheme://host``
string and rejected every legitimate origin. This revision replaces it
with a single regex constraint that mirrors the Pydantic validator in
``app/schemas/admin_widget.py::_validate_origin``:

    ^https?://[^/?# ]+$

The full set of validation rules (no wildcards, no plain-http for non-
localhost, default-port stripping, lowercasing) still lives in the
admin schema — the DB check is a defense-in-depth net that catches
direct INSERTs that bypass the API layer.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008_fix_origin_check_constraint"
down_revision: str | Sequence[str] | None = "0007_content_chunks_pgvector"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the broken constraint from 0004.
    op.execute(
        "ALTER TABLE widget_allowed_origins "
        "DROP CONSTRAINT IF EXISTS ck_widget_allowed_origins_no_path"
    )
    # Add a regex check that allows scheme://host[:port] and nothing else.
    op.execute(
        "ALTER TABLE widget_allowed_origins "
        "ADD CONSTRAINT ck_widget_allowed_origins_shape "
        r"CHECK (origin ~ '^https?://[^/?# ]+$')"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE widget_allowed_origins "
        "DROP CONSTRAINT IF EXISTS ck_widget_allowed_origins_shape"
    )
    # Restore the original broken constraint so downgrade is symmetric.
    op.execute(
        "ALTER TABLE widget_allowed_origins "
        "ADD CONSTRAINT ck_widget_allowed_origins_no_path "
        "CHECK (origin NOT LIKE '%/%/%')"
    )
