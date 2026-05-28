"""Shared visual tokens for the Albert admin app.

Streamlit's built-in theme system is limited, so we layer a small CSS
sheet on top via ``inject_global_css()`` to enforce the minimalism +
bento design: tight section cards, a single primary CTA per page,
semantic state colors, and predictable spacing rhythm (4/8 scale).

Every page module imports ``apply_page_chrome()`` at the top — it sets
``st.set_page_config`` once and injects the CSS sheet.
"""

from __future__ import annotations

import streamlit as st

# --- Semantic color tokens (light theme) ----------------------------------
#
# Token names mirror the design-system roles used in the backend. Avoid
# referencing raw hex anywhere outside this module.
COLORS = {
    "primary": "#2563eb",       # blue-600
    "primary_hover": "#1d4ed8", # blue-700
    "surface": "#ffffff",
    "background": "#f8fafc",    # slate-50
    "border": "#e2e8f0",        # slate-200
    "border_strong": "#cbd5e1", # slate-300
    "text_primary": "#0f172a",  # slate-900
    "text_secondary": "#475569",# slate-600
    "text_muted": "#94a3b8",    # slate-400
    "danger": "#dc2626",        # red-600
    "danger_bg": "#fef2f2",
    "warning": "#d97706",       # amber-600
    "warning_bg": "#fffbeb",
    "success": "#059669",       # emerald-600
    "success_bg": "#ecfdf5",
}


_CSS = f"""
<style>
/* Tight bento layout — each block_container section becomes a card. */
section.main > div.block-container {{
  padding-top: 2rem;
  padding-bottom: 4rem;
  max-width: 1100px;
}}

h1, h2, h3 {{
  color: {COLORS['text_primary']};
  letter-spacing: -0.01em;
}}
h1 {{ font-size: 1.75rem; font-weight: 700; }}
h2 {{ font-size: 1.25rem; font-weight: 600; margin-top: 1.5rem; }}
h3 {{ font-size: 1rem;    font-weight: 600; }}

.albert-section {{
  background: {COLORS['surface']};
  border: 1px solid {COLORS['border']};
  border-radius: 12px;
  padding: 1.25rem 1.5rem;
  margin-bottom: 1rem;
}}
.albert-section + .albert-section {{ margin-top: 0.75rem; }}

.albert-meta {{
  color: {COLORS['text_secondary']};
  font-size: 0.875rem;
  line-height: 1.5;
}}
.albert-muted {{ color: {COLORS['text_muted']}; font-size: 0.8125rem; }}

.albert-badge {{
  display: inline-block;
  padding: 0.125rem 0.5rem;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}}
.albert-badge-success {{ color: {COLORS['success']}; background: {COLORS['success_bg']}; }}
.albert-badge-danger  {{ color: {COLORS['danger']};  background: {COLORS['danger_bg']}; }}
.albert-badge-warning {{ color: {COLORS['warning']}; background: {COLORS['warning_bg']}; }}
.albert-badge-muted   {{ color: {COLORS['text_secondary']}; background: {COLORS['background']}; border: 1px solid {COLORS['border']}; }}

.albert-callout {{
  border: 1px solid {COLORS['warning']};
  background: {COLORS['warning_bg']};
  color: #78350f;
  border-radius: 10px;
  padding: 0.875rem 1rem;
  font-size: 0.9375rem;
}}
.albert-callout-danger {{ border-color: {COLORS['danger']}; background: {COLORS['danger_bg']}; color: #7f1d1d; }}
.albert-callout-info   {{ border-color: {COLORS['border_strong']}; background: {COLORS['background']}; color: {COLORS['text_secondary']}; }}

/* Primary action button — only one per page (visually) */
div.stButton > button[kind="primary"] {{
  background: {COLORS['primary']};
  border-color: {COLORS['primary']};
  font-weight: 600;
  border-radius: 8px;
}}
div.stButton > button[kind="primary"]:hover {{
  background: {COLORS['primary_hover']};
  border-color: {COLORS['primary_hover']};
}}

/* Tabular figures for versions / counts / timestamps */
.albert-mono {{
  font-variant-numeric: tabular-nums;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.875rem;
}}
</style>
"""


def apply_page_chrome(title: str, *, icon: str = "🟦") -> None:
    """Set page config + inject the shared stylesheet.

    Call once at the top of every page module. ``st.set_page_config`` is
    idempotent within a single Streamlit run, so reapplying is cheap.
    """
    st.set_page_config(
        page_title=f"Albert · {title}",
        page_icon=icon,
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={
            "About": "Albert tenant admin — manage widgets, origins, and guardrails.",
        },
    )
    st.markdown(_CSS, unsafe_allow_html=True)


def section(label: str) -> None:
    """Render a bento section heading. Inline so callers stay terse."""
    st.markdown(f"<h2>{label}</h2>", unsafe_allow_html=True)


def callout(message: str, *, level: str = "info") -> None:
    """Render a callout banner. ``level`` ∈ {info, warning, danger}."""
    cls = {
        "info": "albert-callout-info",
        "warning": "",
        "danger": "albert-callout-danger",
    }.get(level, "albert-callout-info")
    st.markdown(
        f'<div class="albert-callout {cls}">{message}</div>',
        unsafe_allow_html=True,
    )


def status_badge(value: str) -> str:
    """Return the HTML for a status pill given a widget status string."""
    cls = {
        "enabled": "albert-badge-success",
        "disabled": "albert-badge-danger",
    }.get(value, "albert-badge-muted")
    return f'<span class="albert-badge {cls}">{value}</span>'
