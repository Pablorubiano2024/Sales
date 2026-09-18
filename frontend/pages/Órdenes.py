"""Página de Órdenes: seguimiento a órdenes pendientes de compra manual al proveedor."""

from __future__ import annotations

import api_client
import streamlit as st
from auth_gate import require_password
from components.tables import render_orders_table
from theme import inject_base_styles

st.set_page_config(page_title="Órdenes", page_icon="📦", layout="wide")
require_password()
inject_base_styles()
st.title("📦 Órdenes")
st.caption(
    "No se mantiene inventario. Cuando se detecta una venta, hay que comprar "
    "al proveedor y hacer que envíe directamente al cliente."
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
        "Aún no hay órdenes. Las órdenes se crean cuando se detecta una venta "
        "en el marketplace para una oportunidad — esta plataforma todavía no "
        "automatiza esa detección (ver el roadmap en PROJECT_CONTEXT.md)."
    )
