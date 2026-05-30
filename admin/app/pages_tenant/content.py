"""Content page — author the knowledge your widget agent answers from (feature 007, US1).

Lists, creates, edits, and deletes this tenant's CMS content pages. The backend
derives ``tenant_id`` from the verified JWT (the client methods take no
``tenant_id``); saved content is re-indexed in the background so the widget agent
can retrieve it. An empty tenant renders a designed empty state.
"""

from __future__ import annotations

import streamlit as st

from app.clients.backend_client import BackendClient, BackendError
from app.lib import ui
from app.lib.auth import handle_backend_error, page_session
from app.lib.theme import status_badge


def _load_pages(client: BackendClient):
    slot = st.empty()
    with slot.container():
        ui.loading_skeleton(4)
    try:
        pages = client.list_cms_pages(limit=200)
    except BackendError as exc:
        slot.empty()
        if handle_backend_error(exc):
            return None
        if ui.error_state(f"Could not load content: {exc}", key="content-retry"):
            st.rerun()
        return None
    slot.empty()
    return pages


def _create_form(client: BackendClient) -> None:
    with st.expander("➕ New content page", expanded=False):
        with st.form("cms-create", clear_on_submit=True):
            title = st.text_input("Title", max_chars=200)
            body = st.text_area("Body", height=200, max_chars=100_000)
            published = st.checkbox("Published (retrievable by the agent)", value=True)
            submitted = st.form_submit_button("Create page")
        if submitted:
            if not title.strip() or not body.strip():
                st.warning("Title and body are both required.")
                return
            try:
                client.create_cms_page(
                    title=title, body=body, is_published=published
                )
            except BackendError as exc:
                if handle_backend_error(exc):
                    return
                st.error(f"Could not create page: {exc}")
                return
            st.success("Page created. It will be retrievable shortly.")
            st.rerun()


def _edit_controls(client: BackendClient, pages) -> None:
    labels = {f"{p.title} ({p.slug})": p for p in pages}
    choice = st.selectbox("Edit a page", options=list(labels.keys()))
    page = labels[choice]
    with st.form(f"cms-edit-{page.id}"):
        new_title = st.text_input("Title", value=page.title, max_chars=200)
        new_body = st.text_area("Body", value=page.body, height=240, max_chars=100_000)
        new_pub = st.checkbox("Published", value=page.is_published)
        col_save, col_del = st.columns(2)
        save = col_save.form_submit_button("Save changes")
        delete = col_del.form_submit_button("Delete page", type="secondary")
    if save:
        if not new_title.strip() or not new_body.strip():
            st.warning("Title and body are both required.")
            return
        try:
            client.update_cms_page(
                page.id, title=new_title, body=new_body, is_published=new_pub
            )
        except BackendError as exc:
            if handle_backend_error(exc):
                return
            st.error(f"Could not save: {exc}")
            return
        st.success("Saved. Re-indexing in the background.")
        st.rerun()
    if delete:
        try:
            client.delete_cms_page(page.id)
        except BackendError as exc:
            if handle_backend_error(exc):
                return
            st.error(f"Could not delete: {exc}")
            return
        st.success("Page deleted.")
        st.rerun()


def main() -> None:
    session = page_session()
    client = BackendClient(token=session.token)

    st.markdown("<h1>Content</h1>", unsafe_allow_html=True)
    st.markdown(
        '<p class="albert-meta">Pages your widget agent answers from. Saved content '
        "is re-indexed automatically. Scoped to your tenant only.</p>",
        unsafe_allow_html=True,
    )

    _create_form(client)

    pages = _load_pages(client)
    if pages is None:
        return

    if not pages:
        ui.empty_state(
            "No content yet",
            description="Create a page above — an FAQ, policy, or product description — "
            "and your agent will answer from it.",
            icon="📝",
        )
        return

    rows = [
        [
            page.updated_at,
            page.title,
            page.slug,
            status_badge("published" if page.is_published else "draft"),
        ]
        for page in pages
    ]
    ui.data_table(["Updated", "Title", "Slug", "Status"], rows, raw_cols=(3,))

    _edit_controls(client, pages)


if __name__ == "__main__":
    main()
