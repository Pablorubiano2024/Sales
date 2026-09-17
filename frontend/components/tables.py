"""Reusable table rendering helpers."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def render_opportunities_table(opportunities: list[dict], products_by_id: dict[str, dict]) -> None:
    if not opportunities:
        st.info("No opportunities match the current filters.")
        return

    rows = []
    for opp in opportunities:
        product = products_by_id.get(opp["product_id"], {})
        rows.append(
            {
                "id": opp["id"],
                "Product": product.get("name", opp["product_id"]),
                "Buy Price": opp["buy_price"],
                "Sell Price": opp["sell_price"],
                "Net Profit": opp["net_profit"],
                "ROI": opp["roi"],
                "Margin": opp["margin"],
                "Risk": opp["risk_score"],
                "AI Score": opp["ai_score"],
                "Status": opp["status"],
            }
        )

    df = pd.DataFrame(rows)
    display_df = df.drop(columns=["id"])
    st.dataframe(
        display_df.style.format(
            {
                "Buy Price": "${:,.0f}",
                "Sell Price": "${:,.0f}",
                "Net Profit": "${:,.0f}",
                "ROI": "{:.1%}",
                "Margin": "{:.1%}",
                "Risk": "{:.2f}",
                "AI Score": "{:.2f}",
            },
            na_rep="—",
        ),
        use_container_width=True,
        hide_index=True,
    )


def render_orders_table(orders: list[dict], products_by_id: dict[str, dict]) -> None:
    if not orders:
        st.info("No orders yet.")
        return

    rows = []
    for order in orders:
        product = products_by_id.get(order["product_id"], {})
        rows.append(
            {
                "Product": product.get("name", order["product_id"]),
                "Selling Price": order["selling_price"],
                "Supplier Price": order["supplier_price"],
                "Expected Profit": order["expected_profit"],
                "Status": order["status"],
                "Shipping": order["customer_shipping_status"],
                "Created": order["created_at"],
            }
        )
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
