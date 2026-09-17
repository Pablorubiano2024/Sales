"""Panel de Arbitraje de Productos — punto de entrada de Streamlit.

Ejecutar con:
    streamlit run frontend/app.py

Capa de presentación únicamente: toda la lógica de negocio vive en el
backend de FastAPI (ver backend/app/services). Esta app solo muestra
datos obtenidos por HTTP.
"""

from __future__ import annotations

import api_client
import streamlit as st
from auth_gate import require_password
from components.metrics import render_dashboard_metrics

st.set_page_config(page_title="Panel de Arbitraje", page_icon="📦", layout="wide")

require_password()

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

st.divider()
st.subheader("Para empezar")
st.markdown(
    """
    Usa las páginas del menú lateral para:
    - **Oportunidades** — revisar, filtrar y analizar oportunidades de arbitraje
    - **Productos** — explorar el catálogo de productos
    - **Órdenes** — hacer seguimiento a órdenes pendientes de compra manual al proveedor
    - **Marketplaces** — ver los canales de venta configurados
    - **Configuración** — ver los umbrales de rentabilidad actuales
    """
)

if not marketplaces:
    st.info(
        "Aún no hay marketplaces configurados. Ejecuta `python scripts/seed.py` "
        "para cargar datos de demostración."
    )
