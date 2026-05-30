"""Pure-function tests for the role-aware navigation resolver (T013, FR-002).

No Streamlit harness: these assert on :func:`nav_entries` (plain ``NavPage``
data). ``build_navigation`` (which constructs ``st.Page`` objects) is smoke-
checked only for count parity so the two builders can never drift.
"""

from __future__ import annotations

from pathlib import Path

from app.lib.nav import build_navigation, nav_entries

_APP_DIR = Path(__file__).resolve().parents[1] / "app"

_EXPECTED_PLATFORM = {
    "Overview",
    "Tenants",
    "Tenant Detail",
    "Cost Overview",
    "Audit Log",
    "Managers",
}
_EXPECTED_TENANT = {
    "Overview",
    "Content",
    "Widgets",
    "Allowed Origins",
    "Guardrails",
    "Embed Snippet",
    "Signing Key",
    "Leads",
    "Escalations",
    "Members",
}


def test_manager_gets_exactly_six_platform_entries() -> None:
    entries = nav_entries("tenant_manager")
    assert len(entries) == 6
    assert {entry.title for entry in entries} == _EXPECTED_PLATFORM
    # All platform pages live under pages_platform/ (never auto-discovered).
    assert all(entry.path.startswith("pages_platform/") for entry in entries)


def test_admin_gets_exactly_ten_tenant_entries() -> None:
    entries = nav_entries("tenant_admin")
    assert len(entries) == 10
    assert {entry.title for entry in entries} == _EXPECTED_TENANT
    assert all(entry.path.startswith("pages_tenant/") for entry in entries)


def test_other_and_unknown_roles_get_no_navigation() -> None:
    assert nav_entries("other") == []
    assert nav_entries("member") == []
    assert nav_entries("") == []


def test_each_surface_has_exactly_one_default_landing() -> None:
    for role in ("tenant_manager", "tenant_admin"):
        defaults = [entry for entry in nav_entries(role) if entry.default]
        assert len(defaults) == 1
        assert defaults[0].title == "Overview"


def test_url_paths_are_unique_within_a_surface() -> None:
    for role in ("tenant_manager", "tenant_admin"):
        url_paths = [entry.url_path for entry in nav_entries(role)]
        assert len(url_paths) == len(set(url_paths))


def test_build_navigation_count_matches_entries() -> None:
    # st.Page construction does not require a running script (paths are not
    # validated at construction), so this is a safe parity smoke check.
    assert len(build_navigation("tenant_manager")) == 6
    assert len(build_navigation("tenant_admin")) == 10
    assert build_navigation("other") == []


def test_no_member_role_surface_exists() -> None:
    # FR-052 (covered-by-design): there is no member-role page directory, so a
    # 'member' can never enumerate an admin surface (the nav resolver also
    # returns [] for it — see test_other_and_unknown_roles_get_no_navigation).
    assert not any(_APP_DIR.glob("pages_member*")), "no member-role surface allowed"


def test_no_platform_page_references_tenant_content_paths() -> None:
    # Defense-in-depth mirror of FR-018: the platform nav must not point at any
    # tenant-content surface module.
    forbidden = ("widgets", "allowed_origins", "guardrails", "signing_key", "leads", "members")
    platform_paths = " ".join(entry.path for entry in nav_entries("tenant_manager"))
    assert not any(fragment in platform_paths for fragment in forbidden)
