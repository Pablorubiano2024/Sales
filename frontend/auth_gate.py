"""Candado simple para el frontend cuando se publica públicamente.

Si `APP_PASSWORD` no está configurado, la app queda abierta (cómodo para
uso local). Si está configurado, pide la contraseña una vez por sesión de
navegador antes de mostrar cualquier página. No es un sistema de usuarios
con cuentas — es un candado de contraseña compartida, del mismo nivel que
`API_AUTH_TOKEN` en el backend.
"""

from __future__ import annotations

import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()


def _get_app_password() -> str | None:
    # st.secrets solo existe si hay un secrets.toml (p. ej. en Streamlit
    # Cloud); si no, se usa la variable de entorno (.env en local).
    try:
        value = st.secrets.get("APP_PASSWORD")
    except Exception:
        value = None
    return value or os.environ.get("APP_PASSWORD") or None


def require_password() -> None:
    """Bloquea el resto de la página hasta que se ingrese la contraseña
    correcta. No hace nada si APP_PASSWORD no está configurado."""
    password = _get_app_password()
    if not password:
        return

    if st.session_state.get("authenticated"):
        return

    st.title("🔒 Acceso al panel")
    entered = st.text_input("Contraseña", type="password")
    if st.button("Entrar"):
        if entered == password:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Contraseña incorrecta.")
    st.stop()
