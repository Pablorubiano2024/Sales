"""Vista de Marketplaces: canales de venta configurados."""

from __future__ import annotations

import api_client
import pandas as pd
import streamlit as st

st.title("🏪 Marketplaces")

try:
    marketplaces = api_client.get_marketplaces()
except api_client.ApiError as exc:
    st.error(str(exc))
    st.stop()

if not marketplaces:
    st.info(
        "Aún no hay marketplaces configurados. Ejecuta `python scripts/seed.py` "
        "para cargar datos de demostración."
    )
else:
    df = pd.DataFrame(marketplaces).rename(
        columns={"name": "Nombre", "country": "País", "active": "Activo"}
    )
    st.dataframe(df, width="stretch", hide_index=True)

st.divider()
st.subheader("MercadoLibre")

try:
    ml_status = api_client.get_mercadolibre_status()
except api_client.ApiError as exc:
    ml_status = None
    st.error(str(exc))

if ml_status and ml_status["connected"]:
    st.success(
        f"Cuenta conectada (usuario MercadoLibre id `{ml_status['external_user_id']}`). "
        f"Permisos otorgados: `{ml_status['scope']}`."
    )
    st.caption(
        "La conexión (OAuth) es real. Publicar, actualizar precio/stock y leer "
        "órdenes todavía no está implementado — solo la autenticación. Ver "
        "backend/app/integrations/mercadolibre.py para el detalle de qué falta."
    )
    st.link_button(
        "Reconectar / cambiar cuenta",
        url=f"{api_client.API_BASE_URL}/api/marketplaces/mercadolibre/authorize",
    )
else:
    st.info(
        "Cuenta de MercadoLibre no conectada todavía. El botón te lleva al flujo real "
        "de autorización de MercadoLibre (OAuth) — inicias sesión con tu cuenta y "
        "autorizas la aplicación."
    )
    st.link_button(
        "Conectar cuenta de MercadoLibre",
        url=f"{api_client.API_BASE_URL}/api/marketplaces/mercadolibre/authorize",
    )
    st.caption(
        "Requiere que el backend tenga ML_CLIENT_ID / ML_CLIENT_SECRET / "
        "ML_REDIRECT_URI configurados (ver .env.example)."
    )
