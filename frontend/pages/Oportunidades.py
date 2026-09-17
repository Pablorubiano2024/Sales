"""Página de Oportunidades: tabla filtrable + vista de detalle con acciones de IA."""

from __future__ import annotations

import api_client
import streamlit as st
from auth_gate import require_password
from components.opportunity_card import render_opportunity_detail
from components.tables import render_opportunities_table
from i18n import OPPORTUNITY_STATUS_LABELS

st.set_page_config(page_title="Oportunidades", page_icon="📈", layout="wide")
require_password()
st.title("📈 Oportunidades")

try:
    products = api_client.get_products(limit=1000)
    opportunities = api_client.get_opportunities(limit=1000)
except api_client.ApiError as exc:
    st.error(str(exc))
    st.stop()

products_by_id = {p["id"]: p for p in products}
categories = sorted({p.get("category") for p in products if p.get("category")})

status_options = {"Todos": None, **{v: k for k, v in OPPORTUNITY_STATUS_LABELS.items()}}

with st.sidebar:
    st.header("Filtros")
    min_roi_pct = st.slider("ROI mínimo (%)", 0, 200, 0, step=5)
    min_profit = st.number_input("Ganancia neta mínima (COP)", value=0, step=5000)
    status_label = st.selectbox("Estado", list(status_options.keys()))
    category_filter = st.selectbox("Categoría", ["Todas", *categories])
    max_risk = st.slider("Riesgo máximo", 0.0, 1.0, 1.0, step=0.05)

status_filter = status_options[status_label]

filtered = opportunities
filtered = [o for o in filtered if o["roi"] >= min_roi_pct / 100]
filtered = [o for o in filtered if o["net_profit"] >= min_profit]
if status_filter is not None:
    filtered = [o for o in filtered if o["status"] == status_filter]
if category_filter != "Todas":
    filtered = [
        o
        for o in filtered
        if products_by_id.get(o["product_id"], {}).get("category") == category_filter
    ]
filtered = [o for o in filtered if o["risk_score"] is None or o["risk_score"] <= max_risk]

render_opportunities_table(filtered, products_by_id)

st.divider()
st.subheader("Detalle de la oportunidad")

if filtered:
    options = {
        f"{products_by_id.get(o['product_id'], {}).get('name', o['product_id'])} "
        f"(ROI {o['roi']:.0%}, neto ${o['net_profit']:,.0f})": o["id"]
        for o in filtered
    }
    selected_label = st.selectbox("Selecciona una oportunidad", list(options.keys()))
    selected_id = options[selected_label]

    try:
        opportunity = api_client.get_opportunity(selected_id)
    except api_client.ApiError as exc:
        st.error(str(exc))
    else:
        product = products_by_id.get(opportunity["product_id"])
        render_opportunity_detail(opportunity, product)
else:
    st.info("Ninguna oportunidad coincide con los filtros actuales.")
