"""Reusable KPI/metric row rendering for the Streamlit dashboard."""

from __future__ import annotations

import streamlit as st


def render_dashboard_metrics(
    total_products: int,
    total_opportunities: int,
    promising_opportunities: int,
    potential_profit: float,
    active_listings: int,
    pending_orders: int,
) -> None:
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Products", total_products)
    col2.metric("Opportunities Found", total_opportunities)
    col3.metric("Promising Opportunities", promising_opportunities)

    col4, col5, col6 = st.columns(3)
    col4.metric("Potential Profit (COP)", f"${potential_profit:,.0f}")
    col5.metric("Active Listings", active_listings)
    col6.metric("Pending Orders", pending_orders)
