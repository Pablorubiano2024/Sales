"""Shared visual styling: a small CSS injection + status color palette,
used consistently across the dashboard, tables and opportunity detail view.

The app ships ONE fixed dark theme via `.streamlit/config.toml`'s
`[theme]` table (`base = "dark"` + explicit dark colors) — every viewer
sees it by default, with no light/dark split to keep in sync.

An earlier version of this file tried to detect the active theme at
runtime via `st.context.theme.type` and switch between a light and a dark
palette. That was dropped after finding, in Streamlit's own source
(`runtime/context.py`, `ContextProxy.theme`): "the theme type may be
incorrect... When the app is first loaded within a session [or] when the
user changes the theme in the settings menu" (tracked upstream as
streamlit/streamlit#11920) — confirmed live: on a fresh page load with
this dark theme active, `st.context.theme.type` reported "light",
producing light-on-dark cards. Since the app now only ships one theme,
detecting it dynamically buys nothing and hits that bug for free, so the
colors below are simply hardcoded for the one theme that exists.

`st.dataframe` only honors literal inline `background-color`/`color` on
Styler cells (no CSS classes, no `var(--...)`, confirmed by inspecting the
rendered DOM — there are no page-level theme CSS custom properties
either), so table cell colors are set directly here rather than in CSS.
"""

from __future__ import annotations

import streamlit as st

# status -> (background, text) hex colors.
OPPORTUNITY_STATUS_COLORS: dict[str, tuple[str, str]] = {
    "approved": ("#14532D", "#86EFAC"),  # green
    "promising": ("#1E3A8A", "#93C5FD"),  # blue
    "review": ("#78350F", "#FCD34D"),  # amber
    "rejected": ("#7F1D1D", "#FCA5A5"),  # red
}

ORDER_STATUS_COLORS: dict[str, tuple[str, str]] = {
    "new": ("#1E3A8A", "#93C5FD"),
    "awaiting_supplier_purchase": ("#78350F", "#FCD34D"),
    "purchased_from_supplier": ("#312E81", "#A5B4FC"),
    "completed": ("#14532D", "#86EFAC"),
    "cancelled": ("#374151", "#D1D5DB"),
}

_DEFAULT_COLOR = ("#374151", "#D1D5DB")


def opportunity_status_palette() -> dict[str, tuple[str, str]]:
    """Full status->(bg, fg) palette, e.g. for a chart color scale."""
    return OPPORTUNITY_STATUS_COLORS


def status_colors(status: str) -> tuple[str, str]:
    return OPPORTUNITY_STATUS_COLORS.get(status, _DEFAULT_COLOR)


def order_status_colors(status: str) -> tuple[str, str]:
    return ORDER_STATUS_COLORS.get(status, _DEFAULT_COLOR)


def status_badge_html(status: str, label: str) -> str:
    bg, fg = status_colors(status)
    return (
        f'<span style="background-color:{bg}; color:{fg}; padding:4px 12px; '
        f"border-radius:999px; font-weight:600; font-size:0.85rem; "
        f'white-space:nowrap;">{label}</span>'
    )


def inject_base_styles() -> None:
    """Call once near the top of every page. Idempotent — safe to call
    multiple times per session (Streamlit re-runs the whole script anyway)."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        html, body, [class*="css"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        }

        [data-testid="stMetric"] {
            background-color: #1E293B;
            border: 1px solid #334155;
            border-radius: 14px;
            padding: 24px 28px;
        }

        [data-testid="stMetricLabel"] {
            font-weight: 500;
            color: #9CA3AF;
            font-size: 1rem;
        }

        [data-testid="stMetricValue"] {
            font-size: 2.1rem;
        }

        h1, h2, h3 {
            font-weight: 700;
        }

        h1 {
            font-size: 2.3rem;
        }

        h3, [data-testid="stMarkdownContainer"] h5 {
            font-size: 1.25rem;
        }

        .block-container {
            padding-top: 3.2rem;
            padding-bottom: 3rem;
            max-width: 1400px;
        }

        /* Top navigation (st.navigation(position="top")): centered instead of
        left-aligned, and a bit larger. The nav row's outer flex container
        (space-between: nav vs. the Deploy/menu button) must stay as-is —
        centering happens one level in, on the inner `.rc-overflow` flex
        container that actually holds the nav links. */
        [data-testid="stToolbar"] .rc-overflow {
            justify-content: center !important;
        }

        [data-testid="stTopNavLink"] {
            font-size: 1.05rem !important;
            padding: 6px 18px !important;
        }

        [data-testid="stHeader"], [data-testid="stToolbar"] {
            height: 68px !important;
        }

        [data-testid="stSidebar"] {
            border-right: 1px solid #334155;
        }

        [data-testid="stVerticalBlockBorderWrapper"] {
            padding: 4px;
        }

        [data-testid="stPageLink"] p {
            font-size: 1.05rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
