"""Ayudas reutilizables para renderizar tablas."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from i18n import opportunity_status_label, order_status_label, shipping_status_label
from theme import order_status_colors, status_colors

_PILL_STYLE = "font-weight:600; border-radius:6px; padding:2px 8px;"


def render_opportunities_table(
    opportunities: list[dict],
    products_by_id: dict[str, dict],
    sources_by_id: dict[str, dict] | None = None,
) -> dict | None:
    """Renders the opportunities table and returns the clicked row's full
    opportunity dict (or None if nothing is selected) — the caller uses
    this to show detail right below the table, no separate picker needed."""
    if not opportunities:
        st.info("Ninguna oportunidad coincide con los filtros actuales.")
        return None

    sources_by_id = sources_by_id or {}
    rows = []
    status_values = []
    for opp in opportunities:
        product = products_by_id.get(opp["product_id"], {})
        source = sources_by_id.get(opp["source_id"], {})
        status_values.append(opp["status"])
        rows.append(
            {
                "Producto": product.get("name", opp["product_id"]),
                "Fuente": source.get("name", "—"),
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

    display_df = pd.DataFrame(rows)
    estado_idx = display_df.columns.get_loc("Estado")

    # `row.name` is the DataFrame's positional index (0..n-1, matching the
    # order `rows`/`status_values` were built in) — kept separate from the
    # displayed columns rather than hidden via Styler.hide(), which
    # st.dataframe doesn't reliably respect for columns.
    def _color_estado(row: pd.Series) -> list[str]:
        styles = [""] * len(row)
        bg, fg = status_colors(status_values[row.name])
        styles[estado_idx] = f"background-color:{bg}; color:{fg}; {_PILL_STYLE}"
        return styles

    styled = display_df.style.format(
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
    ).apply(_color_estado, axis=1)
    event = st.dataframe(
        styled,
        width="stretch",
        hide_index=True,
        key="opportunities_table",
        on_select="rerun",
        selection_mode="single-row",
    )
    selected_rows = event.selection.rows if event and event.selection else []
    if selected_rows:
        return opportunities[selected_rows[0]]
    return None


def render_orders_table(orders: list[dict], products_by_id: dict[str, dict]) -> None:
    if not orders:
        st.info("Aún no hay órdenes.")
        return

    rows = []
    status_values = []
    for order in orders:
        product = products_by_id.get(order["product_id"], {})
        status_values.append(order["status"])
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
    display_df = pd.DataFrame(rows)
    estado_idx = display_df.columns.get_loc("Estado")

    def _color_estado(row: pd.Series) -> list[str]:
        styles = [""] * len(row)
        bg, fg = order_status_colors(status_values[row.name])
        styles[estado_idx] = f"background-color:{bg}; color:{fg}; {_PILL_STYLE}"
        return styles

    styled = display_df.style.format(
        {
            "Precio de venta": "${:,.0f}",
            "Precio proveedor": "${:,.0f}",
            "Ganancia esperada": "${:,.0f}",
        }
    ).apply(_color_estado, axis=1)
    st.dataframe(styled, width="stretch", hide_index=True)
