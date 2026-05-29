"""Static-inspection guard for the tenant surface (T050, FR-025).

The tenant_admin pages MUST NEVER touch a manager-only endpoint. This test
greps every module under ``admin/app/pages_tenant/`` for the forbidden manager
path fragments and fails the build on any match — a structural guarantee that
the tenant surface cannot reach platform/lifecycle endpoints, independent of
runtime behavior.
"""

from __future__ import annotations

from pathlib import Path

_PAGES_DIR = Path(__file__).resolve().parents[1] / "app" / "pages_tenant"

_FORBIDDEN_FRAGMENTS = (
    "/api/v1/tenants",
    "/suspend",
    "/reactivate",
    "/tenants/managers",
    "/tenants/cost/all",
    "/tenants/cost/series",
    "/tenants/audit",
)


def test_pages_tenant_directory_exists() -> None:
    assert _PAGES_DIR.is_dir()


def test_no_tenant_page_references_manager_endpoints() -> None:
    offenders: list[str] = []
    for path in _PAGES_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for fragment in _FORBIDDEN_FRAGMENTS:
            if fragment in text:
                offenders.append(f"{path.name}: {fragment}")
    assert not offenders, (
        "Tenant pages must not reference manager-only endpoints: "
        + ", ".join(offenders)
    )
