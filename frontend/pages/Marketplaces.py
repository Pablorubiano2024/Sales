"""Página de Marketplaces: canales de venta configurados."""

from __future__ import annotations

import api_client
import pandas as pd
import streamlit as st
from auth_gate import require_password

st.set_page_config(page_title="Marketplaces", page_icon="🏪", layout="wide")
require_password()
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
    st.dataframe(df, use_container_width=True, hide_index=True)

st.divider()
st.subheader("MercadoLibre")
st.warning(
    "La publicación en MercadoLibre aún no está implementada. El adaptador de "
    "integración existe como un esqueleto (backend/app/integrations/mercadolibre.py) "
    "pero requiere credenciales de API verificadas y documentación de los endpoints "
    "antes de poder crear o actualizar publicaciones reales."
)
st.button(
    "Conectar cuenta de MercadoLibre",
    disabled=True,
    help="Requiere credenciales OAuth de una app registrada.",
)
