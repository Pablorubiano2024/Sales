"""Marketplaces page: configured selling channels."""

from __future__ import annotations

import api_client
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Marketplaces", page_icon="🏪", layout="wide")
st.title("🏪 Marketplaces")

try:
    marketplaces = api_client.get_marketplaces()
except api_client.ApiError as exc:
    st.error(str(exc))
    st.stop()

if not marketplaces:
    st.info("No marketplaces configured yet. Run `python scripts/seed.py` to load demo data.")
else:
    st.dataframe(pd.DataFrame(marketplaces), use_container_width=True, hide_index=True)

st.divider()
st.subheader("MercadoLibre")
st.warning(
    "MercadoLibre publishing is not implemented yet. The integration adapter "
    "exists as a skeleton (backend/app/integrations/mercadolibre.py) but "
    "requires verified API credentials and endpoint documentation before it "
    "can create or update real listings."
)
st.button("Connect MercadoLibre account", disabled=True, help="Requires OAuth app credentials.")
