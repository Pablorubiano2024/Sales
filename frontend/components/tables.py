"""Ayudas reutilizables para renderizar tablas."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from i18n import opportunity_status_label, order_status_label, shipping_status_label


def render_opportunities_table(opportunities: list[dict], products_by_id: dict[str, dict]) -> None:
    if not opportunities:
        st.info("Ninguna oportunidad coincide con los filtros actuales.")
        return

    rows = []
    for opp in opportunities:
        product = products_by_id.get(opp["product_id"], {})
        rows.append(
            {
                "id": opp["id"],
                "Producto": product.get("name", opp["product_id"]),
                "Precio compra": opp["buy_price"],
                "Precio venta": opp["sell_price"],
                "Ganancia neta": opp["net_profit"],
                "ROI": opp["roi"],
                "Margen": opp["margin"],
                "Riesgo": opp["risk_score"],
                "Puntaje IA": opp["ai_score"],
                "Estado": opportunity_status_label(opp["status"]),
            }
        )

    df = pd.DataFrame(rows)
    display_df = df.drop(columns=["id"])
    st.dataframe(
        display_df.style.format(
            {
                "Precio compra": "${:,.0f}",
                "Precio venta": "${:,.0f}",
                "Ganancia neta": "${:,.0f}",
                "ROI": "{:.1%}",
                "Margen": "{:.1%}",
                "Riesgo": "{:.2f}",
                "Puntaje IA": "{:.2f}",
            },
            na_rep="—",
        ),
        use_container_width=True,
        hide_index=True,
    )


def render_orders_table(orders: list[dict], products_by_id: dict[str, dict]) -> None:
    if not orders:
        st.info("Aún no hay órdenes.")
        return

    rows = []
    for order in orders:
        product = products_by_id.get(order["product_id"], {})
        rows.append(
            {
                "Producto": product.get("name", order["product_id"]),
                "Precio de venta": order["selling_price"],
                "Precio proveedor": order["supplier_price"],
                "Ganancia esperada": order["expected_profit"],
                "Estado": order_status_label(order["status"]),
                "Envío": shipping_status_label(order["customer_shipping_status"]),
                "Creada": order["created_at"],
            }
        )
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
