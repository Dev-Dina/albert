"""Guard: every table with a tenant_id column MUST be covered by erasure (FR-008).

Metadata-based tripwire (no DB) so it runs on every host test pass. The two tables this
feature added to erasure (escalations, tenant_memberships) were each introduced by a
LATER feature without updating erasure — a silent right-to-erasure leak. This test fails
loudly, naming the offending table, if that ever recurs (SC-003).
"""

from __future__ import annotations

import app.db.models  # noqa: F401  — import side effect: populate Base.metadata
from app.db.base import Base
from app.tenancy import erasure


def uncovered_tenant_tables(tenant_tables: set[str], covered: set[str]) -> set[str]:
    """Pure helper: tenant-owned tables (own a tenant_id) not purged by erasure."""
    return tenant_tables - covered


def _covered() -> set[str]:
    return set(erasure._TENANT_TABLES) | set(erasure._OPTIONAL_LEGACY_TABLES)


def _mapped_tenant_tables() -> set[str]:
    return {t.name for t in Base.metadata.tables.values() if "tenant_id" in t.columns}


def test_every_mapped_tenant_id_table_is_covered_by_erasure() -> None:
    """Positive: the current schema is fully covered."""
    uncovered = uncovered_tenant_tables(_mapped_tenant_tables(), _covered())
    assert not uncovered, (
        f"Tenant-owned table(s) {sorted(uncovered)} have a tenant_id column but are not "
        "purged by erasure. Add them to _TENANT_TABLES in app/tenancy/erasure.py — an "
        "uncovered tenant_id table is a right-to-erasure compliance leak (FR-008)."
    )


def test_guard_flags_a_new_uncovered_table() -> None:
    """Negative (SC-003): a future tenant_id table added without erasure coverage is
    reported by name, proving the guard fails loudly rather than silently passing."""
    synthetic = "surprise_new_tenant_table"
    tenant_tables = _mapped_tenant_tables() | {synthetic}
    assert uncovered_tenant_tables(tenant_tables, _covered()) == {synthetic}


def test_escalations_and_memberships_are_now_covered() -> None:
    """Regression lock for this feature: the two previously-missing tables are covered."""
    covered = _covered()
    assert "escalations" in covered
    assert "tenant_memberships" in covered
