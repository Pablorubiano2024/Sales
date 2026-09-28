"""Order sync job (Autopilot Phase 5) — polls real MercadoLibre sales and
routes each new one to a supplier via order_router.py (Sandbox mode).

Like discovery.py/price_monitor.py, this is invoked manually / from a
script for now; a scheduler can call `run_order_sync` directly once one
exists (Phase 7).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.core.logging import get_logger
from backend.app.integrations.mercadolibre import MercadoLibreAdapter
from backend.app.models.marketplace import MarketplaceProduct
from backend.app.models.order import Order
from backend.app.services.order_router import create_order_from_sale

logger = get_logger(__name__)


def run_order_sync(db: Session, adapter: MercadoLibreAdapter, since: str | None = None) -> int:
    """Fetch real MercadoLibre orders and create an internal Order
    (Sandbox mode) for each real sale not already recorded. Returns the
    number of new Orders created."""
    orders = adapter.get_orders(since=since)
    created = 0

    for order_info in orders:
        existing = db.query(Order).filter_by(marketplace_order_id=order_info.external_id).first()
        if existing is not None:
            continue

        if order_info.item_external_id is None:
            logger.warning(
                "Orden real %s sin item_external_id identificable — se omite",
                order_info.external_id,
            )
            continue

        listing = (
            db.query(MarketplaceProduct).filter_by(external_id=order_info.item_external_id).first()
        )
        if listing is None:
            logger.warning(
                "Orden real %s: item %s no corresponde a ninguna publicación registrada",
                order_info.external_id,
                order_info.item_external_id,
            )
            continue

        create_order_from_sale(
            db,
            product_id=listing.product_id,
            selling_price=order_info.total_amount,
            marketplace_order_id=order_info.external_id,
        )
        created += 1
        logger.info(
            "Orden real %s (producto=%s) enrutada en modo Sandbox",
            order_info.external_id,
            listing.product_id,
        )

    return created
