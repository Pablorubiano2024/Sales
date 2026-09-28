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
from backend.app.models.opportunity import Opportunity
from backend.app.models.order import Order
from backend.app.services.order_router import create_order_from_sale

logger = get_logger(__name__)


def _resolve_opportunity_id(db: Session, product_id: str) -> str | None:
    """Best real Opportunity for this Product — the most recently updated
    one, since a product can have more than one Opportunity row (across
    sources). A heuristic, documented rather than hidden: good enough to
    attribute analytics to *a* real opportunity for this product without
    inventing a stronger link this schema doesn't actually have."""
    opportunity = (
        db.query(Opportunity)
        .filter_by(product_id=product_id)
        .order_by(Opportunity.updated_at.desc())
        .first()
    )
    return opportunity.id if opportunity is not None else None


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
            opportunity_id=_resolve_opportunity_id(db, listing.product_id),
        )
        created += 1
        logger.info(
            "Orden real %s (producto=%s) enrutada en modo Sandbox",
            order_info.external_id,
            listing.product_id,
        )

    return created
