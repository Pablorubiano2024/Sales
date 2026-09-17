"""Price monitoring job.

Re-checks current prices for known SourceProducts via their source's
adapter, records PriceHistory, and recomputes any Opportunities tied to
that product/source pair so ROI/margin/status stay current.

Like discovery.py, this is invoked manually / from scripts for now; a
scheduler can call `run_price_monitor` directly once one is introduced.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.core.logging import get_logger
from backend.app.integrations.base import SourceAdapter
from backend.app.models.opportunity import Opportunity
from backend.app.models.price_history import PriceHistory
from backend.app.models.source import SourceProduct
from backend.app.services.arbitrage_engine import recompute_opportunity

logger = get_logger(__name__)


def run_price_monitor(db: Session, source_id: str, adapter: SourceAdapter) -> int:
    """Refresh prices for all SourceProducts belonging to `source_id`.
    Returns the number of SourceProducts updated."""
    source_products = db.query(SourceProduct).filter_by(source_id=source_id).all()
    updated = 0

    for sp in source_products:
        if sp.external_id is None:
            logger.warning("Price monitor: SourceProduct %s has no external_id, skipping", sp.id)
            continue

        current_price = adapter.get_price(sp.external_id)
        if current_price is None:
            logger.warning("Price monitor: no price returned for %s", sp.external_id)
            continue

        if current_price != sp.current_price:
            logger.info(
                "Price change detected for product %s: %s -> %s",
                sp.product_id,
                sp.current_price,
                current_price,
            )

        sp.current_price = current_price
        sp.stock_available = adapter.get_stock(sp.external_id)
        db.add(sp)

        db.add(
            PriceHistory(
                product_id=sp.product_id,
                source_id=sp.source_id,
                price=current_price,
                currency=sp.currency,
            )
        )
        db.commit()

        affected_opportunities = (
            db.query(Opportunity).filter_by(product_id=sp.product_id, source_id=sp.source_id).all()
        )
        for opportunity in affected_opportunities:
            opportunity.buy_price = current_price
            recompute_opportunity(db, opportunity)

        updated += 1

    return updated
