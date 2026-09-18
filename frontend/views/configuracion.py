"""Vista de Configuración: umbrales de rentabilidad actuales y estado de la config."""

from __future__ import annotations

import api_client
import streamlit as st

st.title("⚙️ Configuración")

try:
    settings = api_client.get_settings()
except api_client.ApiError as exc:
    st.error(str(exc))
    st.stop()

col1, col2, col3 = st.columns(3)
col1.metric("ROI mínimo", f"{settings['min_roi']:.0%}")
col2.metric("Ganancia neta mínima", f"${settings['min_net_profit']:,.0f}")
col3.metric("Riesgo máximo", f"{settings['max_risk_score']:.2f}")

st.write("")
col4, col5 = st.columns(2)
col4.metric("Moneda por defecto", settings["default_currency"])
col5.metric("Tasa USD → COP", f"${settings['usd_to_cop_rate']:,.0f}")
st.caption(
    "Se usa para convertir precios de fuentes en USD (como CJdropshipping) a COP "
    "antes de calcular rentabilidad. Revisa la TRM oficial (banrep.gov.co) de vez "
    "en cuando y actualiza `USD_TO_COP_RATE` en tu .env si se ha alejado mucho."
)

st.divider()
st.write(f"**Entorno:** {settings['app_env']}")

if settings["claude_configured"]:
    st.success("El enriquecimiento con Claude está configurado (ANTHROPIC_API_KEY definida).")
else:
    st.warning(
        "El enriquecimiento con Claude NO está configurado. Define ANTHROPIC_API_KEY "
        "en tu .env para habilitar el análisis de oportunidades asistido por IA. La "
        "plataforma funciona sin eso — los cálculos financieros son deterministas y "
        "no dependen de la IA."
    )

st.caption(
    "Estos umbrales se configuran con variables de entorno (MIN_ROI, "
    "MIN_NET_PROFIT, MAX_RISK_SCORE) — ver .env.example. Cambiarlos desde aquí "
    "todavía no está implementado; edita .env y reinicia el backend."
)
