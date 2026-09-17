"""Página de Productos: explorar el catálogo de productos."""

from __future__ import annotations

import api_client
import pandas as pd
import streamlit as st
from auth_gate import require_password

st.set_page_config(page_title="Productos", page_icon="🛒", layout="wide")
require_password()
st.title("🛒 Productos")

try:
    products = api_client.get_products(limit=1000)
except api_client.ApiError as exc:
    st.error(str(exc))
    st.stop()

if not products:
    st.info(
        "Aún no hay productos. Ejecuta `python scripts/seed.py` para cargar datos de demostración."
    )
else:
    df = pd.DataFrame(products)[["sku", "name", "brand", "category", "active", "created_at"]]
    df = df.rename(
        columns={
            "sku": "SKU",
            "name": "Nombre",
            "brand": "Marca",
            "category": "Categoría",
            "active": "Activo",
            "created_at": "Creado",
        }
    )
    st.dataframe(df, use_container_width=True, hide_index=True)

st.divider()
st.subheader("Agregar un producto")
with st.form("new_product"):
    sku = st.text_input("SKU")
    name = st.text_input("Nombre")
    brand = st.text_input("Marca", value="")
    category = st.text_input("Categoría", value="")
    submitted = st.form_submit_button("Crear producto")

if submitted:
    if not sku or not name:
        st.warning("SKU y nombre son obligatorios.")
    else:
        try:
            api_client.create_product(
                {
                    "sku": sku,
                    "name": name,
                    "brand": brand or None,
                    "category": category or None,
                }
            )
            st.success(f"Producto '{name}' creado.")
            st.rerun()
        except api_client.ApiError as exc:
            st.error(str(exc))
