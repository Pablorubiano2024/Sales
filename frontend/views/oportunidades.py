"""Vista de Oportunidades: tabla filtrable + detalle con acciones de IA."""

from __future__ import annotations

import api_client
import streamlit as st
from components.opportunity_card import render_opportunity_detail
from components.tables import render_opportunities_table
from i18n import OPPORTUNITY_STATUS_LABELS

st.title("📈 Oportunidades")

try:
    products = api_client.get_products(limit=1000)
    opportunities = api_client.get_opportunities(limit=1000)
    sources = api_client.get_sources()
except api_client.ApiError as exc:
    st.error(str(exc))
    st.stop()

products_by_id = {p["id"]: p for p in products}
sources_by_id = {s["id"]: s for s in sources}
categories = sorted({p.get("category") for p in products if p.get("category")})

status_options = {"Todos": None, **{v: k for k, v in OPPORTUNITY_STATUS_LABELS.items()}}

source_options = {"Todas": None, **{s["name"]: s["id"] for s in sources}}

with st.sidebar:
    st.header("Filtros")
    min_roi_pct = st.slider("ROI mínimo (%)", 0, 200, 0, step=5)
    min_profit = st.number_input("Ganancia neta mínima (COP)", value=0, step=5000)
    status_label = st.selectbox("Estado", list(status_options.keys()))
    source_label = st.selectbox("Fuente", list(source_options.keys()))
    category_filter = st.selectbox("Categoría", ["Todas", *categories])
    max_risk = st.slider("Riesgo máximo", 0.0, 1.0, 1.0, step=0.05)

status_filter = status_options[status_label]
source_filter = source_options[source_label]

filtered = opportunities
filtered = [o for o in filtered if o["roi"] >= min_roi_pct / 100]
filtered = [o for o in filtered if o["net_profit"] >= min_profit]
if status_filter is not None:
    filtered = [o for o in filtered if o["status"] == status_filter]
if source_filter is not None:
    filtered = [o for o in filtered if o["source_id"] == source_filter]
if category_filter != "Todas":
    filtered = [
        o
        for o in filtered
        if products_by_id.get(o["product_id"], {}).get("category") == category_filter
    ]
filtered = [o for o in filtered if o["risk_score"] is None or o["risk_score"] <= max_risk]

st.info(
    '💡 **"Precio venta" no significa lo mismo para todas las fuentes.** En CJdropshipping '
    "(mayorista) es un estimado (compra × 1.8, sin verificar contra MercadoLibre). En Falabella "
    "(minorista) es el precio normal real que ellos mismos reportan junto al descuento — dato "
    "de mercado real, aunque tampoco es un precio verificado en MercadoLibre específicamente. "
    'Revisa la columna "Fuente" para saber cuál aplica a cada fila.'
)
st.caption("Haz clic en una fila de la tabla para ver el detalle completo abajo.")
selected_opportunity = render_opportunities_table(filtered, products_by_id, sources_by_id)

st.divider()

if selected_opportunity:
    product = products_by_id.get(selected_opportunity["product_id"])
    render_opportunity_detail(selected_opportunity, product)
elif filtered:
    st.info("☝️ Selecciona una fila de la tabla de arriba para ver el detalle.")
