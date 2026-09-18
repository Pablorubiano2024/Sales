"""Vista de Inicio: dashboard con métricas y resumen general.

Nota: `st.set_page_config`, `require_password()` e `inject_base_styles()`
viven una sola vez en `frontend/app.py` (el shell de navegación) — no se
repiten aquí porque `st.navigation().run()` ejecuta este módulo como parte
del mismo script run, no como una página independiente.
"""

from __future__ import annotations

import altair as alt
import api_client
import pandas as pd
import streamlit as st
from components.metrics import render_dashboard_metrics
from i18n import opportunity_status_label
from theme import opportunity_status_palette

st.title("📦 Panel de Arbitraje de Productos")
st.caption(
    "Descubrir → Analizar → Calcular → Publicar → Vender → Comprar → Enviar → Medir ganancia"
)

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
    active_listings=0,  # aún no hay publicación en marketplaces
    pending_orders=len(pending_orders),
)

st.write("")

if opportunities:
    status_order = ["approved", "promising", "review", "rejected"]
    counts = {s: 0 for s in status_order}
    for opp in opportunities:
        counts[opp["status"]] = counts.get(opp["status"], 0) + 1

    chart_df = pd.DataFrame(
        [
            {"Estado": opportunity_status_label(s), "Cantidad": counts[s]}
            for s in status_order
            if counts[s] > 0
        ]
    )
    palette = opportunity_status_palette()
    color_scale = alt.Scale(
        domain=[opportunity_status_label(s) for s in status_order],
        range=[palette[s][1] for s in status_order],
    )

    col_chart, col_summary = st.columns([2, 1])
    with col_chart:
        st.markdown("##### Oportunidades por estado")
        chart = (
            alt.Chart(chart_df)
            .mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6, size=48)
            .encode(
                x=alt.X("Estado:N", title=None, sort=None),
                y=alt.Y("Cantidad:Q", title=None),
                color=alt.Color("Estado:N", scale=color_scale, legend=None),
                tooltip=["Estado", "Cantidad"],
            )
            .properties(height=240)
        )
        st.altair_chart(chart, width="stretch")
    with col_summary:
        st.markdown("##### Resumen")
        for s in status_order:
            if counts[s] > 0:
                st.write(f"**{opportunity_status_label(s)}:** {counts[s]}")

st.divider()

st.subheader("Para empezar")
link_cols = st.columns(5)
links = [
    ("views/oportunidades.py", "📈", "Oportunidades", "revisar, filtrar y analizar"),
    ("views/productos.py", "🛒", "Productos", "explorar el catálogo"),
    ("views/ordenes.py", "📦", "Órdenes", "seguimiento de compras al proveedor"),
    ("views/marketplaces.py", "🏪", "Marketplaces", "canales de venta configurados"),
    ("views/configuracion.py", "⚙️", "Configuración", "umbrales de rentabilidad"),
]
for col, (page, icon, name, desc) in zip(link_cols, links, strict=True):
    with col, st.container(border=True):
        st.page_link(page, label=f"**{icon} {name}**", width="stretch")
        st.caption(desc)

if not marketplaces:
    st.info(
        "Aún no hay marketplaces configurados. Ejecuta `python scripts/seed.py` "
        "para cargar datos de demostración."
    )
