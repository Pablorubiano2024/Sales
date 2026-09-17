"""Traducciones de los valores de estado que vienen del backend.

El backend/la API mantienen los valores en inglés (son el contrato, no
deberían cambiar por un tema de idioma de la interfaz); aquí solo se
traducen para mostrarlos en el frontend.
"""

from __future__ import annotations

OPPORTUNITY_STATUS_LABELS = {
    "rejected": "Rechazada",
    "review": "En revisión",
    "promising": "Prometedora",
    "approved": "Aprobada",
}

ORDER_STATUS_LABELS = {
    "new": "Nueva",
    "awaiting_supplier_purchase": "Esperando compra al proveedor",
    "purchased_from_supplier": "Comprada al proveedor",
    "completed": "Completada",
    "cancelled": "Cancelada",
}

SHIPPING_STATUS_LABELS = {
    "not_shipped": "Sin enviar",
    "shipped": "Enviado",
    "in_transit": "En tránsito",
    "delivered": "Entregado",
    "returned": "Devuelto",
}


def opportunity_status_label(value: str) -> str:
    return OPPORTUNITY_STATUS_LABELS.get(value, value)


def order_status_label(value: str) -> str:
    return ORDER_STATUS_LABELS.get(value, value)


def shipping_status_label(value: str) -> str:
    return SHIPPING_STATUS_LABELS.get(value, value)
