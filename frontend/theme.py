"""Shared visual styling: a small CSS injection + status color palette used
consistently across the dashboard, tables and opportunity detail view.

Streamlit's per-widget styling options are limited, so this keeps things
simple: one color per opportunity status, applied as pandas Styler
background colors in tables and as HTML "pill" badges elsewhere.
"""

from __future__ import annotations

import streamlit as st

# Status -> (background, text) hex colors. Chosen for readable contrast in
# both a plain background and as a pill badge.
OPPORTUNITY_STATUS_COLORS: dict[str, tuple[str, str]] = {
    "approved": ("#DCFCE7", "#166534"),  # green
    "promising": ("#DBEAFE", "#1E40AF"),  # blue
    "review": ("#FEF3C7", "#92400E"),  # amber
    "rejected": ("#FEE2E2", "#991B1B"),  # red
}

ORDER_STATUS_COLORS: dict[str, tuple[str, str]] = {
    "new": ("#DBEAFE", "#1E40AF"),  # blue
    "awaiting_supplier_purchase": ("#FEF3C7", "#92400E"),  # amber
    "purchased_from_supplier": ("#E0E7FF", "#3730A3"),  # indigo
    "completed": ("#DCFCE7", "#166534"),  # green
    "cancelled": ("#F3F4F6", "#374151"),  # gray
}

_DEFAULT_COLOR = ("#F3F4F6", "#374151")  # neutral gray fallback


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
            background-color: #FAFAFA;
            border: 1px solid #E5E7EB;
            border-radius: 12px;
            padding: 16px 20px;
        }

        [data-testid="stMetricLabel"] {
            font-weight: 500;
            color: #6B7280;
        }

        h1, h2, h3 {
            font-weight: 700;
        }

        [data-testid="stSidebar"] {
            border-right: 1px solid #E5E7EB;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
