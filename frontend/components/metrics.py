"""Renderizado reutilizable de la fila de métricas (KPIs) del panel."""

from __future__ import annotations

import streamlit as st


def render_dashboard_metrics(
    total_products: int,
    total_opportunities: int,
    promising_opportunities: int,
    potential_profit: float,
    active_listings: int,
    pending_orders: int,
) -> None:
    col1, col2, col3 = st.columns(3)
    col1.metric("Productos totales", total_products)
    col2.metric("Oportunidades encontradas", total_opportunities)
    col3.metric("Oportunidades prometedoras", promising_opportunities)

    col4, col5, col6 = st.columns(3)
    col4.metric("Ganancia potencial (COP)", f"${potential_profit:,.0f}")
    col5.metric("Publicaciones activas", active_listings)
    col6.metric("Órdenes pendientes", pending_orders)
