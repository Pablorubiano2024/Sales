"""Vista de Autopilot (Fase 3): cola de borradores de publicación,
generados a partir de Opportunities aprobadas. La publicación real ahora
es completamente automática (scripts/publish_approved_opportunities.py,
vía GitHub Actions) — "Aprobar" aquí es solo informativo (marca que un
humano ya lo revisó); "Rechazar" sí es real: un borrador rechazado se
salta en cada corrida automática hasta que alguien lo regenere.
"""

from __future__ import annotations

import json

import api_client
import pandas as pd
import streamlit as st
from i18n import listing_draft_status_label

st.title("🤖 Autopilot")

try:
    opportunities = api_client.get_opportunities(status_filter="approved", limit=1000)
    drafts = api_client.get_listing_drafts()
    products = api_client.get_products(limit=1000)
except api_client.ApiError as exc:
    st.error(str(exc))
    st.stop()

products_by_id = {p["id"]: p for p in products}
opportunities_by_id = {o["id"]: o for o in opportunities}
drafted_opportunity_ids = {d["opportunity_id"] for d in drafts}

st.subheader("1. Oportunidades aprobadas sin borrador")
st.caption(
    "Genera un borrador de publicación con datos reales de la fuente (título, "
    "descripción, categoría, comisión) para revisarlo aquí — la corrida automática "
    "igual genera y publica el suyo propio si no haces nada."
)
without_draft = [o for o in opportunities if o["id"] not in drafted_opportunity_ids]
if not without_draft:
    st.info("Todas las oportunidades aprobadas ya tienen un borrador.")
else:
    for opp in without_draft:
        product = products_by_id.get(opp["product_id"], {})
        col_name, col_score, col_action = st.columns([3, 1, 1])
        col_name.write(f"**{product.get('name', opp['product_id'])}**")
        score = opp.get("confidence_score")
        col_score.metric("Confianza", f"{score}%" if score is not None else "—")
        if col_action.button("Generar borrador", key=f"gen-{opp['id']}"):
            try:
                with st.spinner("Consultando datos reales de la fuente..."):
                    api_client.generate_listing_draft(opp["id"])
                st.success("Borrador generado.")
                st.rerun()
            except api_client.ApiError as exc:
                st.error(str(exc))

st.divider()

st.subheader("2. Cola de aprobación")
status_options = {
    "Todos": None,
    "Borrador": "draft",
    "Listo para publicar": "ready",
    "Rechazado": "rejected",
}
status_label = st.selectbox("Filtrar por estado", list(status_options.keys()))
status_filter = status_options[status_label]

visible_drafts = (
    drafts if status_filter is None else [d for d in drafts if d["status"] == status_filter]
)

if not visible_drafts:
    st.info("No hay borradores con ese filtro.")
else:
    table_rows = []
    for d in visible_drafts:
        opp = opportunities_by_id.get(d["opportunity_id"])
        confidence = opp.get("confidence_score") if opp else None
        table_rows.append(
            {
                "Título": d["title"],
                "Precio": d["price"],
                "Categoría ML": d.get("category_id") or "—",
                "Estado": listing_draft_status_label(d["status"]),
                # Pre-formatted as a plain string (like "Categoría ML"
                # above) rather than a numeric column with NaN — an
                # all-missing numeric column renders its NaNs as the
                # literal text "None" in st.dataframe's own grid, ignoring
                # the Styler's na_rep (na_rep only affects HTML/notebook
                # rendering, confirmed live in this app 2026-09-26).
                "Confianza": f"{confidence}%" if confidence is not None else "—",
            }
        )
    df = pd.DataFrame(table_rows)
    st.dataframe(
        df.style.format({"Precio": "${:,.0f}"}),
        width="stretch",
        hide_index=True,
    )

    labels = [f"{d['title']} — {listing_draft_status_label(d['status'])}" for d in visible_drafts]
    selected_label = st.selectbox("Selecciona un borrador para revisar", ["—", *labels])
    if selected_label != "—":
        draft = visible_drafts[labels.index(selected_label)]
        opportunity = opportunities_by_id.get(draft["opportunity_id"])
        if opportunity is None:
            try:
                opportunity = api_client.get_opportunity(draft["opportunity_id"])
            except api_client.ApiError:
                opportunity = None

        st.markdown(f"### {draft['title']}")
        col_price, col_cat, col_status = st.columns(3)
        col_price.metric("Precio", f"${draft['price']:,.0f}")
        col_cat.metric("Categoría ML", draft.get("category_id") or "—")
        col_status.metric("Estado", listing_draft_status_label(draft["status"]))

        if draft.get("description"):
            with st.expander("Descripción", expanded=False):
                st.text(draft["description"])

        if draft.get("bullets"):
            try:
                bullets = json.loads(draft["bullets"])
                if bullets:
                    st.write("**Características:**")
                    for b in bullets:
                        st.write(f"- {b}")
            except (json.JSONDecodeError, TypeError):
                pass

        if draft.get("attributes"):
            try:
                attrs = json.loads(draft["attributes"])
                commission_pct = attrs.get("commission_pct")
                commission_text = (
                    f"{commission_pct:.1%}"
                    if commission_pct is not None
                    else "no disponible (conecta la cuenta de MercadoLibre)"
                )
                st.caption(
                    f"Marca: {attrs.get('brand', '—')} · Modelo: {attrs.get('model', '—')} · "
                    f"Comisión real: {commission_text}"
                )
            except (json.JSONDecodeError, TypeError):
                pass

        if draft.get("image_urls"):
            try:
                image_urls = json.loads(draft["image_urls"])
                if image_urls:
                    st.image(image_urls, width=150)
            except (json.JSONDecodeError, TypeError):
                pass

        if opportunity is not None:
            st.divider()
            st.write("**Por qué esta oportunidad (Confidence Engine):**")
            score = opportunity.get("confidence_score")
            if score is None:
                st.caption("Todavía no se ha calculado un puntaje de confianza.")
            else:
                st.metric("Confianza", f"{score}%")
                if opportunity.get("confidence_breakdown"):
                    try:
                        breakdown = json.loads(opportunity["confidence_breakdown"])
                        for factor in breakdown:
                            label, points = factor["label"], factor["points"]
                            st.write(f"- **{label}** (+{points}): {factor['reasoning']}")
                    except (json.JSONDecodeError, TypeError, KeyError):
                        pass

            with st.expander("Validación (Opportunity Validator)", expanded=False):
                refresh_live = st.checkbox(
                    "Consultar stock/precio real de la fuente ahora",
                    key=f"refresh-{draft['id']}",
                )
                try:
                    validation = api_client.validate_opportunity(
                        opportunity["id"], refresh_live=refresh_live
                    )
                    overall_passed = validation["overall_passed"]
                    icon = "✅" if overall_passed else "⚠️"
                    summary = "OK" if overall_passed else "con observaciones"
                    st.write(f"{icon} **Resultado general:** {summary}")
                    for check in validation["checks"]:
                        symbol = {"True": "✅", "False": "❌", "None": "⏸️"}[str(check["passed"])]
                        st.write(f"{symbol} `{check['name']}`: {check['detail']}")
                except api_client.ApiError as exc:
                    st.error(str(exc))

        st.divider()
        col_approve, col_reject, col_source = st.columns(3)
        if col_approve.button(
            "✅ Aprobar",
            key=f"approve-{draft['id']}",
            width="stretch",
            help="Solo informativo: marca que ya lo revisaste. La publicación automática "
            "no espera esto.",
        ):
            try:
                api_client.approve_listing_draft(draft["id"])
                st.success("Marcado como revisado.")
                st.rerun()
            except api_client.ApiError as exc:
                st.error(str(exc))

        with col_reject.popover(
            "❌ Rechazar",
            width="stretch",
            help="Esto sí es real: la publicación automática se salta este borrador hasta "
            "que lo regeneres.",
        ):
            reason = st.text_input("Motivo del rechazo", key=f"reason-{draft['id']}")
            if st.button("Confirmar rechazo", key=f"confirm-reject-{draft['id']}"):
                if not reason:
                    st.warning("Escribe un motivo.")
                else:
                    try:
                        api_client.reject_listing_draft(draft["id"], reason)
                        st.success("Borrador rechazado — la publicación automática lo saltará.")
                        st.rerun()
                    except api_client.ApiError as exc:
                        st.error(str(exc))

        source_url = opportunity.get("source_url") if opportunity else None
        col_source.link_button(
            "🛒 Ver proveedor",
            source_url or "about:blank",
            disabled=not source_url,
            width="stretch",
        )

st.divider()

st.subheader("3. Simulador de Capital")
st.caption(
    "Proyecta ventas potenciales, rotación de capital y ganancia mensual usando datos "
    "reales de tus oportunidades aprobadas — no números inventados."
)
with st.form("capital_simulator"):
    col_capital, col_purchases, col_margin = st.columns(3)
    capital = col_capital.number_input(
        "Capital disponible (COP)", min_value=0, value=5000000, step=100000
    )
    max_daily_purchases = col_purchases.number_input(
        "Máximo de compras diarias", min_value=1, value=5, step=1
    )
    min_margin_pct = col_margin.slider("Margen mínimo (%)", 0, 100, 20, step=5)
    submitted = st.form_submit_button("Simular")

if submitted:
    try:
        result = api_client.simulate_capital(
            capital=float(capital),
            max_daily_purchases=int(max_daily_purchases),
            min_margin=min_margin_pct / 100,
        )
    except api_client.ApiError as exc:
        st.error(str(exc))
    else:
        if not result.get("time_to_sale_is_real_data"):
            st.info(
                f"⏸️ Todavía no hay ventas reales completadas — el tiempo de rotación usa un "
                f"supuesto por defecto de {result['avg_time_to_sale_days']:.0f} días. Esto se "
                "vuelve automáticamente un dato real en cuanto se registren ventas."
            )

        col1, col2, col3 = st.columns(3)
        col1.metric("Compras/día sostenibles (promedio)", f"{result['daily_purchases']:.2f}")
        col2.metric("Ganancia mensual", f"${result['monthly_profit']:,.0f}")
        col3.metric("ROI mensual", f"{result['monthly_roi']:.1%}")

        col4, col5, col6 = st.columns(3)
        col4.metric("Capital desplegado/día", f"${result['daily_capital_deployed']:,.0f}")
        col5.metric("Rotaciones de capital/mes", f"{result['capital_rotations_per_month']:.1f}")
        days_to_double = result.get("days_to_double_capital")
        col6.metric(
            "Días para duplicar capital",
            f"{days_to_double:.0f}" if days_to_double is not None else "—",
        )

        if result["daily_purchases"] < 1:
            st.caption(
                "Menos de 1 compra/día en promedio: con este capital y esta rotación, compra "
                "en tandas cada varios días en vez de todos los días."
            )

        st.caption(
            f"Basado en {result['qualifying_opportunities']} oportunidades aprobadas reales con "
            f"margen ≥ {min_margin_pct}% — precio de compra promedio "
            f"${result['avg_buy_price']:,.0f}, margen promedio {result['avg_margin']:.1%}, "
            f"rotación estimada {result['avg_time_to_sale_days']:.1f} días."
        )

st.divider()

st.subheader("4. Analytics")
st.caption(
    "Qué tan bien está funcionando el sistema en la práctica — datos reales, nunca simulados."
)
try:
    analytics = api_client.get_analytics_summary()
except api_client.ApiError as exc:
    st.error(str(exc))
else:
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Detectadas", analytics["detected_count"])
    a2.metric("Publicadas", analytics["published_count"])
    a3.metric("Vendidas", analytics["sold_count"])
    a4.metric("Expiradas", analytics["expired_count"])

    if analytics["sold_count"] == 0:
        st.info(
            "Todavía no hay ventas reales completadas — estas métricas se llenan solas "
            "en cuanto haya."
        )
    else:
        b1, b2, b3 = st.columns(3)
        time_to_sale = analytics.get("avg_time_to_sale_days")
        b1.metric("Tiempo promedio a la venta", f"{time_to_sale:.1f} días" if time_to_sale else "—")
        est_margin = analytics.get("avg_estimated_margin")
        real_margin = analytics.get("avg_real_margin")
        b2.metric(
            "Margen estimado promedio", f"{est_margin:.1%}" if est_margin is not None else "—"
        )
        b3.metric("Margen real promedio", f"{real_margin:.1%}" if real_margin is not None else "—")

    recal = analytics.get("confidence_recalibration") or {}
    if recal.get("directionally_correct") is not None:
        icon = "✅" if recal["directionally_correct"] else "⚠️"
        direction = "sí" if recal["directionally_correct"] else "no"
        st.caption(
            f"{icon} ¿El Confidence Score predice ventas reales? {direction} — "
            f"score promedio en ventas: {recal['avg_score_sold']:.0f}, "
            f"en expiradas: {recal['avg_score_expired']:.0f} "
            f"({recal['sold_count']} vendidas, {recal['expired_count']} expiradas analizadas)."
        )
