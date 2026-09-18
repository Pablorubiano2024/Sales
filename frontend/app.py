"""Panel de Arbitraje de Productos — punto de entrada de Streamlit.

Ejecutar con:
    streamlit run frontend/app.py

Este archivo es solo el "shell" de navegación (config de página, candado,
estilos, y la barra de navegación arriba — `st.navigation(position="top")`).
El contenido real de cada sección vive en `frontend/views/`. Capa de
presentación únicamente: toda la lógica de negocio vive en el backend de
FastAPI (ver backend/app/services).
"""

from __future__ import annotations

import streamlit as st
from auth_gate import require_password
from theme import inject_base_styles

st.set_page_config(page_title="Panel de Arbitraje", page_icon="📦", layout="wide")

require_password()
inject_base_styles()

pages = [
    st.Page("views/inicio.py", title="Inicio", icon="📦", default=True),
    st.Page("views/oportunidades.py", title="Oportunidades", icon="📈"),
    st.Page("views/productos.py", title="Productos", icon="🛒"),
    st.Page("views/ordenes.py", title="Órdenes", icon="📦"),
    st.Page("views/marketplaces.py", title="Marketplaces", icon="🏪"),
    st.Page("views/configuracion.py", title="Configuración", icon="⚙️"),
]

navigation = st.navigation(pages, position="top")
navigation.run()
