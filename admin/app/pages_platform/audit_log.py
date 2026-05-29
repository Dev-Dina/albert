"""Audit Log — single cross-tenant newest-first timeline (FR-016).

One vertical timeline backed by ``list_audit`` (cross-tenant). No tenant
picker. Each entry shows actor email, action, target tenant slug, and
timestamp. Designed empty state when there are no entries. A "Load older"
control pages back with the keyset cursor.
"""

from __future__ import annotations

import streamlit as st

from app.clients.backend_client import BackendClient, BackendError
from app.lib import ui
from app.lib.auth import handle_backend_error, page_session

_PAGE_SIZE = 50
_ACCUM_KEY = "albert.audit_entries"
_CURSOR_KEY = "albert.audit_cursor"


def main() -> None:
    session = page_session()
    client = BackendClient(token=session.token)
    st.markdown(
        "<h1>Audit log</h1>"
        '<p class="albert-meta">Lifecycle activity across all tenants, newest '
        "first.</p>",
        unsafe_allow_html=True,
    )

    if _ACCUM_KEY not in st.session_state:
        st.session_state[_ACCUM_KEY] = []
        st.session_state[_CURSOR_KEY] = None
        _load_more(client, first=True)

    if st.button("Refresh", key="audit-refresh"):
        st.session_state[_ACCUM_KEY] = []
        st.session_state[_CURSOR_KEY] = None
        _load_more(client, first=True)

    entries = st.session_state[_ACCUM_KEY]
    if not entries:
        ui.empty_state(
            "No audit activity yet",
            description="Provision, suspend, reactivate, or erase a tenant to see entries here.",
        )
        return

    ui.timeline(
        [
            {
                "title": entry.action,
                "meta": " · ".join(
                    part
                    for part in (
                        entry.actor_email,
                        entry.target_tenant_slug,
                        entry.created_at,
                    )
                    if part
                ),
                "body": _format_meta(entry.meta),
            }
            for entry in entries
        ]
    )

    # Offer paging back only while the last page was full (more may exist).
    if st.session_state.get(_CURSOR_KEY) is not None:
        if st.button("Load older", key="audit-more"):
            _load_more(client)


def _format_meta(meta: dict) -> str:
    if not meta:
        return ""
    return ", ".join(f"{k}={v}" for k, v in meta.items())


def _load_more(client: BackendClient, *, first: bool = False) -> None:
    before_id = None if first else st.session_state.get(_CURSOR_KEY)
    try:
        page = client.list_audit(limit=_PAGE_SIZE, before_id=before_id)
    except BackendError as exc:
        if handle_backend_error(exc):
            return
        if ui.error_state(f"Couldn't load the audit log: {exc}", key="audit-retry"):
            st.rerun()
        return
    st.session_state[_ACCUM_KEY].extend(page)
    # When a full page returns, keep the cursor so "Load older" can continue.
    st.session_state[_CURSOR_KEY] = page[-1].entry_id if len(page) == _PAGE_SIZE else None


if __name__ == "__main__":
    main()
