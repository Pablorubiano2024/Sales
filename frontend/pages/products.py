"""Products page: browse the product catalog."""

from __future__ import annotations

import api_client
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Products", page_icon="🛒", layout="wide")
st.title("🛒 Products")

try:
    products = api_client.get_products(limit=1000)
except api_client.ApiError as exc:
    st.error(str(exc))
    st.stop()

if not products:
    st.info("No products yet. Run `python scripts/seed.py` to load demo data.")
else:
    df = pd.DataFrame(products)[["sku", "name", "brand", "category", "active", "created_at"]]
    st.dataframe(df, use_container_width=True, hide_index=True)

st.divider()
st.subheader("Add a product")
with st.form("new_product"):
    sku = st.text_input("SKU")
    name = st.text_input("Name")
    brand = st.text_input("Brand", value="")
    category = st.text_input("Category", value="")
    submitted = st.form_submit_button("Create product")

if submitted:
    if not sku or not name:
        st.warning("SKU and name are required.")
    else:
        try:
            api_client.create_product(
                {
                    "sku": sku,
                    "name": name,
                    "brand": brand or None,
                    "category": category or None,
                }
            )
            st.success(f"Product '{name}' created.")
            st.rerun()
        except api_client.ApiError as exc:
            st.error(str(exc))
