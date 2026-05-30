"""Role -> navigation resolver for explicit ``st.navigation`` registration.

Streamlit's auto-discovered ``pages/`` directory would enumerate *every*
page for *every* signed-in user, leaking the wrong role's surface into the
sidebar. Instead each role's pages live under ``pages_platform/`` /
``pages_tenant/`` (never auto-discovered) and are registered explicitly here
so the sidebar is a real role boundary, not just a visual one (FR-002).

``nav_entries(role)`` is the pure resolver (plain :class:`NavPage` data) used
by tests; ``build_navigation(role)`` maps those entries to ``st.Page`` objects
for ``st.navigation`` in ``main.py``. Both derive from the same spec tables, so
the counts can never drift:

* ``tenant_manager`` -> 6 entries (Overview + 5 platform pages)
* ``tenant_admin``   -> 10 entries (Overview + 9 tenant pages)
* ``other``          -> 0 entries (wrong-role view; no navigation)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NavPage:
    """A single navigation registration (one source of truth per page)."""

    title: str
    icon: str
    path: str  # relative to admin/app/ (the st.navigation entrypoint dir)
    url_path: str
    default: bool = False


# Platform surface (tenant_manager) — Overview landing + 5 capability pages.
_PLATFORM_PAGES: tuple[NavPage, ...] = (
    NavPage("Overview", ":material/dashboard:", "pages_platform/overview.py", "overview", default=True),
    NavPage("Tenants", ":material/apartment:", "pages_platform/tenants.py", "tenants"),
    NavPage("Tenant Detail", ":material/info:", "pages_platform/tenant_detail.py", "tenant-detail"),
    NavPage("Cost Overview", ":material/payments:", "pages_platform/cost_overview.py", "cost-overview"),
    NavPage("Audit Log", ":material/history:", "pages_platform/audit_log.py", "audit-log"),
    NavPage("Managers", ":material/admin_panel_settings:", "pages_platform/managers.py", "managers"),
)

# Tenant surface (tenant_admin) — Overview landing + 8 capability pages.
_TENANT_PAGES: tuple[NavPage, ...] = (
    NavPage("Overview", ":material/dashboard:", "pages_tenant/overview.py", "overview", default=True),
    NavPage("Content", ":material/article:", "pages_tenant/content.py", "content"),
    NavPage("Widgets", ":material/widgets:", "pages_tenant/widgets.py", "widgets"),
    NavPage("Allowed Origins", ":material/shield:", "pages_tenant/allowed_origins.py", "allowed-origins"),
    NavPage("Guardrails", ":material/policy:", "pages_tenant/guardrails.py", "guardrails"),
    NavPage("Embed Snippet", ":material/code:", "pages_tenant/embed_snippet.py", "embed-snippet"),
    NavPage("Signing Key", ":material/key:", "pages_tenant/signing_key.py", "signing-key"),
    NavPage("Leads", ":material/contacts:", "pages_tenant/leads.py", "leads"),
    NavPage("Escalations", ":material/support_agent:", "pages_tenant/escalations.py", "escalations"),
    NavPage("Members", ":material/group:", "pages_tenant/members.py", "members"),
)


def nav_entries(role: str) -> list[NavPage]:
    """Pure resolver: role -> the exact navigation entries for that surface."""
    if role == "tenant_manager":
        return list(_PLATFORM_PAGES)
    if role == "tenant_admin":
        return list(_TENANT_PAGES)
    return []


def build_navigation(role: str) -> list:
    """Map :func:`nav_entries` to ``st.Page`` objects for ``st.navigation``."""
    import streamlit as st

    return [
        st.Page(
            entry.path,
            title=entry.title,
            icon=entry.icon,
            url_path=entry.url_path,
            default=entry.default,
        )
        for entry in nav_entries(role)
    ]
