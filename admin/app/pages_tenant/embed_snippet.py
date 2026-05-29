"""Embed Snippet page — per-widget copy-ready ``<script>`` line.

Migrated from ``pages/4_Embed_Snippet.py`` to the ``st.navigation`` model and
upgraded per FR-021 / US2 scenario 2:

* the snippet renders through ``lib/ui.code_block`` (Pygments highlighting);
* a one-click copy button uses the Clipboard API;
* a live preview iframe runs with ``sandbox="allow-scripts"`` ONLY (no
  ``allow-same-origin``) so the embed can execute without gaining access to the
  admin origin.
"""

from __future__ import annotations

import html
import json

import streamlit as st
import streamlit.components.v1 as components

from app.clients.backend_client import BackendClient, BackendError
from app.lib import ui
from app.lib.auth import handle_backend_error, page_session
from app.lib.theme import callout, section


def _render_copy_button(snippet: str, key: str) -> None:
    """A one-click copy button (Clipboard API) for the snippet."""
    # The snippet contains a literal "</script>" which would close the OUTER
    # script tag prematurely; escape "</" to "<\/" — the same trick frameworks
    # use for inline JSON.
    encoded = json.dumps(snippet).replace("</", "<\\/")
    markup = f"""
    <style>
      .albert-copy-btn {{
        background: #2563eb; color: white; border: none; padding: 0.4rem 0.9rem;
        border-radius: 6px; font-size: 0.85rem; font-weight: 600; cursor: pointer;
      }}
      .albert-copy-btn:hover {{ background: #1d4ed8; }}
      .albert-copy-btn.copied {{ background: #059669; }}
    </style>
    <button id="copy-{key}" class="albert-copy-btn">Copy snippet</button>
    <script>
      (function() {{
        const btn = document.getElementById("copy-{key}");
        const text = {encoded};
        if (!btn) return;
        btn.addEventListener("click", async () => {{
          try {{
            await navigator.clipboard.writeText(text);
            btn.textContent = "Copied";
            btn.classList.add("copied");
            setTimeout(() => {{ btn.textContent = "Copy snippet"; btn.classList.remove("copied"); }}, 1500);
          }} catch (err) {{ btn.textContent = "Press Ctrl+C"; }}
        }});
      }})();
    </script>
    """
    components.html(markup, height=56)


def _render_preview(snippet: str) -> None:
    """Live preview inside a sandboxed iframe (scripts only, no same-origin)."""
    doc = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>body{font-family:system-ui,sans-serif;margin:1rem;color:#0f172a;}</style>"
        "</head><body>" + snippet + "</body></html>"
    )
    srcdoc = html.escape(doc, quote=True)
    iframe = (
        f'<iframe sandbox="allow-scripts" srcdoc="{srcdoc}" '
        'style="width:100%;height:260px;border:1px solid #e2e8f0;border-radius:10px;"></iframe>'
    )
    components.html(iframe, height=290)


def main() -> None:
    session = page_session()
    client = BackendClient(token=session.token)

    st.markdown("<h1>Embed snippet</h1>", unsafe_allow_html=True)
    st.markdown(
        '<p class="albert-meta">Paste the snippet into your site\'s HTML, '
        "just before <code>&lt;/body&gt;</code>. Make sure the host origin "
        "is on your allowed-origins list.</p>",
        unsafe_allow_html=True,
    )

    slot = st.empty()
    with slot.container():
        ui.loading_skeleton(2)

    try:
        widgets = client.list_widgets()
    except BackendError as exc:
        slot.empty()
        if handle_backend_error(exc):
            return
        if ui.error_state(f"Could not load widgets: {exc}", key="embed-retry"):
            st.rerun()
        return

    slot.empty()

    if not widgets:
        ui.empty_state(
            "No widgets yet",
            description="Create one from the Widgets page first.",
            icon="🪟",
        )
        st.page_link("pages_tenant/widgets.py", label="Go to Widgets", icon="🪟")
        return

    options = {f"{w.name}  ({w.public_widget_id})": w for w in widgets}
    label = st.selectbox("Choose widget", options=list(options.keys()))
    if label is None:
        return
    widget = options[label]

    try:
        snippet = client.get_embed_snippet(widget.id)
    except BackendError as exc:
        if handle_backend_error(exc):
            return
        callout(f"Could not fetch snippet: {exc}", level="danger")
        return

    section("Copy-ready snippet")
    ui.code_block(snippet.snippet, language="html")
    _render_copy_button(snippet.snippet, key=widget.id)

    section("Live preview")
    st.markdown(
        '<p class="albert-meta">Rendered in a sandboxed iframe '
        "(<code>allow-scripts</code> only).</p>",
        unsafe_allow_html=True,
    )
    _render_preview(snippet.snippet)

    section("Details")
    st.markdown(
        f'<div class="albert-meta">'
        f"<strong>Loader URL:</strong> <code>{snippet.loader_url}</code><br>"
        f"<strong>Widget id:</strong> <code>{snippet.data_widget_id}</code>"
        "</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
