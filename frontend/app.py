"""Product Arbitrage Dashboard — Streamlit entrypoint.

Run with:
    streamlit run frontend/app.py

Presentation layer only: all business logic lives in the FastAPI backend
(see backend/app/services). This app just renders data fetched over HTTP.
"""

from __future__ import annotations

import api_client
import streamlit as st
from components.metrics import render_dashboard_metrics

st.set_page_config(page_title="Product Arbitrage Dashboard", page_icon="📦", layout="wide")

st.title("📦 Product Arbitrage Dashboard")
st.caption("Discover → Analyze → Calculate → Publish → Sell → Purchase → Ship → Track Profit")

try:
    api_client.get_health()
except api_client.ApiError as exc:
    st.error(str(exc))
    st.stop()

try:
    products = api_client.get_products(limit=1000)
    opportunities = api_client.get_opportunities(limit=1000)
    orders = api_client.get_orders(limit=1000)
    marketplaces = api_client.get_marketplaces()
except api_client.ApiError as exc:
    st.error(str(exc))
    st.stop()

promising_statuses = {"promising", "approved"}
promising = [o for o in opportunities if o["status"] in promising_statuses]
potential_profit = sum(o["net_profit"] for o in promising)
pending_statuses = {"new", "awaiting_supplier_purchase", "purchased_from_supplier"}
pending_orders = [o for o in orders if o["status"] in pending_statuses]

render_dashboard_metrics(
    total_products=len(products),
    total_opportunities=len(opportunities),
    promising_opportunities=len(promising),
    potential_profit=potential_profit,
    active_listings=0,  # no marketplace publishing implemented yet
    pending_orders=len(pending_orders),
)

st.divider()
st.subheader("Getting started")
st.markdown(
    """
    Use the pages in the sidebar to:
    - **Opportunities** — review, filter and analyze arbitrage opportunities
    - **Products** — browse the product catalog
    - **Orders** — track orders awaiting manual supplier purchase
    - **Marketplaces** — see configured selling channels
    - **Settings** — view current profitability thresholds
    """
)

if not marketplaces:
    st.info("No marketplaces configured yet. Run `python scripts/seed.py` to load demo data.")
