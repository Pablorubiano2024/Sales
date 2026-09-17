"""Detailed opportunity view with action buttons."""

from __future__ import annotations

import json

import api_client
import streamlit as st


def render_opportunity_detail(opportunity: dict, product: dict | None) -> None:
    product_name = product.get("name") if product else opportunity["product_id"]
    st.subheader(product_name)
    st.caption(f"Opportunity ID: {opportunity['id']}")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Net Profit", f"${opportunity['net_profit']:,.0f}")
    col2.metric("ROI", f"{opportunity['roi']:.1%}")
    col3.metric("Margin", f"{opportunity['margin']:.1%}")
    col4.metric("Status", opportunity["status"].upper())

    with st.expander("Cost breakdown", expanded=False):
        st.write(
            {
                "Buy price": opportunity["buy_price"],
                "Sell price": opportunity["sell_price"],
                "Marketplace fee": opportunity["marketplace_fee"],
                "Shipping cost": opportunity["shipping_cost"],
                "Tax cost": opportunity["tax_cost"],
                "Payment cost": opportunity["payment_cost"],
                "Other cost": opportunity["other_cost"],
                "Gross profit": opportunity["gross_profit"],
            }
        )

    if opportunity.get("ai_analysis"):
        with st.expander("AI analysis", expanded=True):
            try:
                analysis = json.loads(opportunity["ai_analysis"])
                st.write(f"**Recommendation:** {analysis.get('recommendation')}")
                st.write(analysis.get("reasoning", ""))
                warnings = analysis.get("warnings") or []
                if warnings:
                    for w in warnings:
                        st.warning(w)
            except (json.JSONDecodeError, TypeError):
                st.text(opportunity["ai_analysis"])
    else:
        st.caption("No AI analysis yet.")

    st.divider()
    b1, b2, b3, b4 = st.columns(4)

    if b1.button("Analyze with Claude", key=f"analyze-{opportunity['id']}"):
        try:
            with st.spinner("Calling Claude..."):
                api_client.analyze_opportunity(
                    {"opportunity_id": opportunity["id"], "use_ai": True}
                )
            st.success("Analysis updated.")
            st.rerun()
        except api_client.ApiError as exc:
            st.error(str(exc))

    # NOTE: mark reviewed / approve / reject and marketplace publishing are
    # placeholders. Status changes are currently driven by the deterministic
    # opportunity engine + AI enrichment, not manual overrides — wiring a
    # manual-override endpoint is a natural next step (see PROJECT_CONTEXT.md).
    b2.button(
        "Mark as reviewed",
        key=f"review-{opportunity['id']}",
        disabled=True,
        help="Not implemented yet: requires a manual-override API endpoint.",
    )
    b3.button(
        "Approve",
        key=f"approve-{opportunity['id']}",
        disabled=True,
        help="Not implemented yet: requires a manual-override API endpoint.",
    )
    b4.button(
        "Reject",
        key=f"reject-{opportunity['id']}",
        disabled=True,
        help="Not implemented yet: requires a manual-override API endpoint.",
    )

    st.button(
        "Publish to MercadoLibre",
        key=f"publish-{opportunity['id']}",
        disabled=True,
        help="Not implemented: MercadoLibre integration requires verified API credentials.",
    )
