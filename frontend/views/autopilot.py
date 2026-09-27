"""Vista de Autopilot (Fase 3): cola de aprobación de borradores de
publicación, generados a partir de Opportunities aprobadas. Aprobar solo
mueve un borrador a "listo" — publicar de verdad sigue siendo un paso
explícito y separado (scripts/publish_approved_opportunities.py), tal
como se pidió: "no publicar inmediatamente".
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
    "descripción, categoría, comisión) — no publica nada todavía."
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
        if col_approve.button("✅ Aprobar", key=f"approve-{draft['id']}", width="stretch"):
            try:
                api_client.approve_listing_draft(draft["id"])
                st.success("Borrador aprobado (listo para publicar).")
                st.rerun()
            except api_client.ApiError as exc:
                st.error(str(exc))

        with col_reject.popover("❌ Rechazar", width="stretch"):
            reason = st.text_input("Motivo del rechazo", key=f"reason-{draft['id']}")
            if st.button("Confirmar rechazo", key=f"confirm-reject-{draft['id']}"):
                if not reason:
                    st.warning("Escribe un motivo.")
                else:
                    try:
                        api_client.reject_listing_draft(draft["id"], reason)
                        st.success("Borrador rechazado.")
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
