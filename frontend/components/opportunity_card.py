"""Vista detallada de una oportunidad con botones de acción."""

from __future__ import annotations

import json

import api_client
import streamlit as st
from i18n import opportunity_status_label
from theme import status_badge_html


def render_opportunity_detail(opportunity: dict, product: dict | None) -> None:
    product_name = product.get("name") if product else opportunity["product_id"]

    title_col, badge_col = st.columns([4, 1])
    with title_col:
        st.subheader(product_name)
        st.caption(f"ID de oportunidad: {opportunity['id']}")
    with badge_col:
        badge_label = opportunity_status_label(opportunity["status"]).upper()
        badge_html = status_badge_html(opportunity["status"], badge_label)
        st.markdown(
            f'<div style="text-align:right; padding-top:8px;">{badge_html}</div>',
            unsafe_allow_html=True,
        )

    col1, col2, col3 = st.columns(3)
    col1.metric("Ganancia neta", f"${opportunity['net_profit']:,.0f}")
    col2.metric("ROI", f"{opportunity['roi']:.1%}")
    col3.metric("Margen", f"{opportunity['margin']:.1%}")

    if opportunity.get("source_url"):
        st.link_button(
            "🛒 Comprar en la fuente",
            opportunity["source_url"],
            help="Ábrelo en cuanto haya una venta en MercadoLibre.",
        )

    st.info(
        "💡 El **precio de venta** usado aquí es una estimación (multiplicador sobre el "
        "precio de compra) — todavía no viene de una búsqueda real en MercadoLibre. Antes "
        "de publicar o comprar con dinero real, verifica manualmente contra 2-3 "
        "publicaciones genéricas (sin marca reconocida) similares en MercadoLibre: la "
        "dispersión de precios entre genéricos y marcas conocidas es grande."
    )

    with st.expander("Desglose de costos", expanded=False):
        st.write(
            {
                "Precio de compra": opportunity["buy_price"],
                "Precio de venta (estimado)": opportunity["sell_price"],
                "Comisión del marketplace": opportunity["marketplace_fee"],
                "Costo de envío": opportunity["shipping_cost"],
                "Impuestos": opportunity["tax_cost"],
                "Costo de pago": opportunity["payment_cost"],
                "Otros costos": opportunity["other_cost"],
                "Ganancia bruta": opportunity["gross_profit"],
            }
        )

    if opportunity.get("ai_analysis"):
        with st.expander("Análisis de IA", expanded=True):
            try:
                analysis = json.loads(opportunity["ai_analysis"])
                st.write(f"**Recomendación:** {analysis.get('recommendation')}")
                st.write(analysis.get("reasoning", ""))
                warnings = analysis.get("warnings") or []
                if warnings:
                    for w in warnings:
                        st.warning(w)
            except (json.JSONDecodeError, TypeError):
                st.text(opportunity["ai_analysis"])
    else:
        st.caption("Todavía no hay análisis de IA.")

    st.divider()

    if st.button("🤖 Analizar con Claude", key=f"analyze-{opportunity['id']}", width="stretch"):
        try:
            with st.spinner("Consultando a Claude..."):
                api_client.analyze_opportunity(
                    {"opportunity_id": opportunity["id"], "use_ai": True}
                )
            st.success("Análisis actualizado.")
            st.rerun()
        except api_client.ApiError as exc:
            st.error(str(exc))

    # NOTA: marcar como revisada / aprobar / rechazar y publicar en un
    # marketplace son marcadores de posición. El estado hoy lo decide el
    # motor determinista de oportunidades + el enriquecimiento con IA, no
    # una anulación manual — un endpoint de anulación manual es el siguiente
    # paso natural (ver PROJECT_CONTEXT.md). Agrupadas en un expander
    # colapsado para no llenar la pantalla de botones que no hacen nada.
    with st.expander("Más acciones (próximamente)", expanded=False):
        b2, b3, b4, b5 = st.columns(4)
        b2.button(
            "Marcar como revisada",
            key=f"review-{opportunity['id']}",
            disabled=True,
            help="Aún no implementado: requiere un endpoint de anulación manual en la API.",
        )
        b3.button(
            "Aprobar",
            key=f"approve-{opportunity['id']}",
            disabled=True,
            help="Aún no implementado: requiere un endpoint de anulación manual en la API.",
        )
        b4.button(
            "Rechazar",
            key=f"reject-{opportunity['id']}",
            disabled=True,
            help="Aún no implementado: requiere un endpoint de anulación manual en la API.",
        )
        b5.button(
            "Publicar en MercadoLibre",
            key=f"publish-{opportunity['id']}",
            disabled=True,
            help=(
                "No implementado: la integración con MercadoLibre requiere "
                "credenciales de API verificadas."
            ),
        )
