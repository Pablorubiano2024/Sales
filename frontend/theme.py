"""Shared visual styling: a small CSS injection + status color palettes,
used consistently across the dashboard, tables and opportunity detail view.

Both a light and a dark palette are defined. `get_theme_type()` reads
`st.context.theme.type` — Streamlit's own record of the viewer's *active*
theme (their explicit Light/Dark choice, or "Use system setting" already
resolved by their browser) — so colors picked here always match whatever
Streamlit itself is rendering with, verified via `.streamlit/config.toml`'s
`[theme.light]` / `[theme.dark]` tables (Streamlit's documented mechanism
for switchable themes) rather than guessed CSS media queries.

`st.dataframe` only honors literal inline `background-color`/`color` on
Styler cells (no CSS classes, no `var(--...)`, confirmed by inspecting the
rendered DOM — there are no page-level theme CSS custom properties either),
so table cell colors are picked in Python per-render instead of in CSS.

Caveat verified live: switching Light/Dark from Streamlit's menu is an
instant client-side change for Streamlit's own widgets, but this module's
colors are computed at Python script-run time — they sync on the *next*
rerun (any widget interaction, a page load, or the menu's own "Rerun"),
not the instant the theme is switched. Normal usage (set a theme once,
then use the app) never notices this; it only shows up mid-interaction
in a live demo.
"""

from __future__ import annotations

import streamlit as st


def get_theme_type() -> str:
    """'light' or 'dark' — the viewer's current active Streamlit theme."""
    try:
        return st.context.theme.type or "light"
    except Exception:
        return "light"


# status -> (background, text) hex colors, per theme.
_OPPORTUNITY_STATUS_COLORS_LIGHT: dict[str, tuple[str, str]] = {
    "approved": ("#DCFCE7", "#166534"),  # green
    "promising": ("#DBEAFE", "#1E40AF"),  # blue
    "review": ("#FEF3C7", "#92400E"),  # amber
    "rejected": ("#FEE2E2", "#991B1B"),  # red
}
_OPPORTUNITY_STATUS_COLORS_DARK: dict[str, tuple[str, str]] = {
    "approved": ("#14532D", "#86EFAC"),
    "promising": ("#1E3A8A", "#93C5FD"),
    "review": ("#78350F", "#FCD34D"),
    "rejected": ("#7F1D1D", "#FCA5A5"),
}

_ORDER_STATUS_COLORS_LIGHT: dict[str, tuple[str, str]] = {
    "new": ("#DBEAFE", "#1E40AF"),
    "awaiting_supplier_purchase": ("#FEF3C7", "#92400E"),
    "purchased_from_supplier": ("#E0E7FF", "#3730A3"),
    "completed": ("#DCFCE7", "#166534"),
    "cancelled": ("#F3F4F6", "#374151"),
}
_ORDER_STATUS_COLORS_DARK: dict[str, tuple[str, str]] = {
    "new": ("#1E3A8A", "#93C5FD"),
    "awaiting_supplier_purchase": ("#78350F", "#FCD34D"),
    "purchased_from_supplier": ("#312E81", "#A5B4FC"),
    "completed": ("#14532D", "#86EFAC"),
    "cancelled": ("#374151", "#D1D5DB"),
}

_DEFAULT_LIGHT = ("#F3F4F6", "#374151")
_DEFAULT_DARK = ("#374151", "#D1D5DB")


def opportunity_status_palette() -> dict[str, tuple[str, str]]:
    """Full status->(bg, fg) palette for the current theme (e.g. for a
    chart color scale)."""
    return (
        _OPPORTUNITY_STATUS_COLORS_DARK
        if get_theme_type() == "dark"
        else _OPPORTUNITY_STATUS_COLORS_LIGHT
    )


def status_colors(status: str) -> tuple[str, str]:
    default = _DEFAULT_DARK if get_theme_type() == "dark" else _DEFAULT_LIGHT
    return opportunity_status_palette().get(status, default)


def order_status_colors(status: str) -> tuple[str, str]:
    dark = get_theme_type() == "dark"
    palette = _ORDER_STATUS_COLORS_DARK if dark else _ORDER_STATUS_COLORS_LIGHT
    default = _DEFAULT_DARK if dark else _DEFAULT_LIGHT
    return palette.get(status, default)


def status_badge_html(status: str, label: str) -> str:
    bg, fg = status_colors(status)
    return (
        f'<span style="background-color:{bg}; color:{fg}; padding:4px 12px; '
        f"border-radius:999px; font-weight:600; font-size:0.85rem; "
        f'white-space:nowrap;">{label}</span>'
    )


def inject_base_styles() -> None:
    """Call once near the top of every page. Idempotent — safe to call
    multiple times per session (Streamlit re-runs the whole script anyway).
    Picks light/dark variants of the small bits of custom CSS that
    `.streamlit/config.toml`'s theme tables don't cover."""
    dark = get_theme_type() == "dark"
    card_bg = "#1E293B" if dark else "#FAFAFA"
    card_border = "#334155" if dark else "#E5E7EB"
    label_color = "#9CA3AF" if dark else "#6B7280"

    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        html, body, [class*="css"] {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        }}

        [data-testid="stMetric"] {{
            background-color: {card_bg};
            border: 1px solid {card_border};
            border-radius: 12px;
            padding: 16px 20px;
        }}

        [data-testid="stMetricLabel"] {{
            font-weight: 500;
            color: {label_color};
        }}

        h1, h2, h3 {{
            font-weight: 700;
        }}

        [data-testid="stSidebar"] {{
            border-right: 1px solid {card_border};
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
