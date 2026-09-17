"""Orders page: track orders awaiting manual supplier purchase."""

from __future__ import annotations

import api_client
import streamlit as st
from components.tables import render_orders_table

st.set_page_config(page_title="Orders", page_icon="📦", layout="wide")
st.title("📦 Orders")
st.caption(
    "No inventory is held. When a sale is detected, purchase from the "
    "supplier and have it shipped directly to the customer."
)

try:
    products = api_client.get_products(limit=1000)
    orders = api_client.get_orders(limit=1000)
except api_client.ApiError as exc:
    st.error(str(exc))
    st.stop()

products_by_id = {p["id"]: p for p in products}
render_orders_table(orders, products_by_id)

if not orders:
    st.info(
        "No orders yet. Orders are created when a marketplace sale is detected "
        "for an opportunity — this platform does not yet automate that "
        "detection (see PROJECT_CONTEXT.md roadmap)."
    )
