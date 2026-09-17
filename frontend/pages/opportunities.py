"""Opportunities page: filterable table + detail view with AI/analysis actions."""

from __future__ import annotations

import api_client
import streamlit as st
from components.opportunity_card import render_opportunity_detail
from components.tables import render_opportunities_table

st.set_page_config(page_title="Opportunities", page_icon="📈", layout="wide")
st.title("📈 Opportunities")

try:
    products = api_client.get_products(limit=1000)
    opportunities = api_client.get_opportunities(limit=1000)
except api_client.ApiError as exc:
    st.error(str(exc))
    st.stop()

products_by_id = {p["id"]: p for p in products}
categories = sorted({p.get("category") for p in products if p.get("category")})

with st.sidebar:
    st.header("Filters")
    min_roi_pct = st.slider("Minimum ROI (%)", 0, 200, 0, step=5)
    min_profit = st.number_input("Minimum net profit (COP)", value=0, step=5000)
    status_filter = st.selectbox("Status", ["All", "rejected", "review", "promising", "approved"])
    category_filter = st.selectbox("Category", ["All", *categories])
    max_risk = st.slider("Maximum risk", 0.0, 1.0, 1.0, step=0.05)

filtered = opportunities
filtered = [o for o in filtered if o["roi"] >= min_roi_pct / 100]
filtered = [o for o in filtered if o["net_profit"] >= min_profit]
if status_filter != "All":
    filtered = [o for o in filtered if o["status"] == status_filter]
if category_filter != "All":
    filtered = [
        o
        for o in filtered
        if products_by_id.get(o["product_id"], {}).get("category") == category_filter
    ]
filtered = [o for o in filtered if o["risk_score"] is None or o["risk_score"] <= max_risk]

render_opportunities_table(filtered, products_by_id)

st.divider()
st.subheader("Opportunity detail")

if filtered:
    options = {
        f"{products_by_id.get(o['product_id'], {}).get('name', o['product_id'])} "
        f"(ROI {o['roi']:.0%}, net ${o['net_profit']:,.0f})": o["id"]
        for o in filtered
    }
    selected_label = st.selectbox("Select an opportunity", list(options.keys()))
    selected_id = options[selected_label]

    try:
        opportunity = api_client.get_opportunity(selected_id)
    except api_client.ApiError as exc:
        st.error(str(exc))
    else:
        product = products_by_id.get(opportunity["product_id"])
        render_opportunity_detail(opportunity, product)
else:
    st.info("No opportunities match the current filters.")
