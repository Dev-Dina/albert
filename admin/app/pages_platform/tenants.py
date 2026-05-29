"""Tenants — list, create, and lifecycle actions (FR-010, FR-011, FR-012, FR-013).

The list shows lifecycle status only (no tenant content). "Create tenant"
validates inline before any backend call. Suspend and Erase are gated by the
shared typed-slug confirmation (``ui.destructive_confirm``, T029); Reactivate
is a simple confirm.
"""

from __future__ import annotations

import re

import streamlit as st

from app.clients.backend_client import BackendClient, BackendError
from app.lib import ui
from app.lib.auth import handle_backend_error, page_session

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_name(value: str) -> str | None:
    return None if value.strip() else "Tenant name is required."


def _validate_email(value: str) -> str | None:
    return None if _EMAIL_RE.match(value.strip()) else "Enter a valid email address."


def _validate_password(value: str) -> str | None:
    return None if len(value) >= 8 else "Password must be at least 8 characters."


def _status_label(status: str) -> str:
    return {
        "active": "albert-badge-success",
        "suspended": "albert-badge-warning",
        "erased": "albert-badge-danger",
    }.get(status, "albert-badge-muted")


def _render_list(client: BackendClient) -> list:
    slot = st.empty()
    with slot.container():
        ui.loading_skeleton(4)
    try:
        tenants = client.list_tenants(limit=200)
    except BackendError as exc:
        slot.empty()
        if handle_backend_error(exc):
            return []
        if ui.error_state(f"Couldn't load tenants: {exc}", key="tn-retry"):
            st.rerun()
        return []

    slot.empty()
    st.markdown("<h2>Tenants</h2>", unsafe_allow_html=True)
    if not tenants:
        ui.empty_state(
            "No tenants yet",
            description="Create the first tenant below to get started.",
        )
        return tenants

    rows = [
        [
            t.name,
            t.slug,
            f'<span class="albert-badge {_status_label(t.status)}">{t.status}</span>',
            (t.created_at or "")[:10],
        ]
        for t in tenants
    ]
    ui.data_table(
        ["Name", "Slug", "Status", "Created"], rows, raw_cols=(2,)
    )
    return tenants


def _render_create(client: BackendClient) -> None:
    st.markdown("<h2>Create tenant</h2>", unsafe_allow_html=True)
    st.markdown(
        '<p class="albert-meta">Provisions a tenant and invites its first '
        "admin. The platform operator never logs into the tenant.</p>",
        unsafe_allow_html=True,
    )
    name, name_ok = ui.inline_validated_input(
        "Tenant name", validator=_validate_name, key="ct-name"
    )
    email, email_ok = ui.inline_validated_input(
        "First admin email", validator=_validate_email, key="ct-email"
    )
    password, pw_ok = ui.inline_validated_input(
        "First admin password",
        validator=_validate_password,
        key="ct-pw",
        password=True,
        help="At least 8 characters. The first admin can change it after signing in.",
    )
    if st.button(
        "Create tenant", type="primary", disabled=not (name_ok and email_ok and pw_ok)
    ):
        try:
            created = client.create_tenant(
                name=name.strip(),
                first_admin_email=email.strip(),
                first_admin_password=password,
            )
        except BackendError as exc:
            if not handle_backend_error(exc):
                st.error(f"Could not create tenant: {exc}")
            return
        st.success(f"Created tenant '{created.name}' ({created.slug}).")
        st.rerun()


def _render_lifecycle(client: BackendClient, tenants: list) -> None:
    if not tenants:
        return
    st.markdown("<h2>Lifecycle actions</h2>", unsafe_allow_html=True)
    by_label = {f"{t.name} ({t.slug}) — {t.status}": t for t in tenants}
    choice = st.selectbox("Select a tenant", list(by_label.keys()))
    tenant = by_label[choice]
    st.markdown(
        f'Current status: <span class="albert-badge {_status_label(tenant.status)}">'
        f"{tenant.status}</span>",
        unsafe_allow_html=True,
    )

    if tenant.status == "erased":
        st.info("This tenant is erased. No further lifecycle actions are available.")
        return

    options = ["Suspend", "Erase"] if tenant.status == "active" else ["Reactivate", "Erase"]
    action = st.radio("Action", options, horizontal=True, key=f"act-{tenant.tenant_id}")

    if action == "Reactivate":
        if st.button("Reactivate tenant", type="primary", key=f"react-{tenant.tenant_id}"):
            _run_action(client, "reactivate", tenant)
        return

    confirmed = ui.destructive_confirm(
        action_label=f"{action} tenant",
        target=tenant.slug,
        key=f"{action}-{tenant.tenant_id}",
        prompt=(
            "Type the slug to confirm permanent erasure."
            if action == "Erase"
            else "Type the slug to confirm suspension."
        ),
    )
    if confirmed:
        _run_action(client, action.lower(), tenant)


def _run_action(client: BackendClient, action: str, tenant) -> None:
    try:
        if action == "suspend":
            client.suspend_tenant(tenant.tenant_id)
        elif action == "reactivate":
            client.reactivate_tenant(tenant.tenant_id)
        elif action == "erase":
            client.erase_tenant(tenant.tenant_id)
    except BackendError as exc:
        if not handle_backend_error(exc):
            st.error(f"Action failed: {exc}")
        return
    st.success(f"{action.capitalize()} succeeded for '{tenant.slug}'.")
    st.rerun()


def main() -> None:
    session = page_session()
    client = BackendClient(token=session.token)
    st.markdown("<h1>Tenants</h1>", unsafe_allow_html=True)
    tenants = _render_list(client)
    _render_create(client)
    _render_lifecycle(client, tenants)


if __name__ == "__main__":
    main()
