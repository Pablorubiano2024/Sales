"""Product discovery job.

Searches a SourceAdapter for candidate products, matches them against the
existing catalog (or creates new Products), and evaluates arbitrage
opportunities against a given marketplace selling price.

This is currently invoked manually / from scripts (see scripts/seed.py for
an example of exercising the same pipeline). It is written so a future
scheduler (cron, APScheduler, a task queue, etc.) can call `run_discovery`
directly without changes — no scheduling infrastructure is wired in yet,
per the MVP scope.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.core.logging import get_logger
from backend.app.integrations.base import SourceAdapter
from backend.app.models.product import Product
from backend.app.models.source import Source, SourceProduct
from backend.app.schemas.opportunity import OpportunityCreate
from backend.app.services.arbitrage_engine import evaluate_opportunity
from backend.app.services.product_matcher import find_best_match

logger = get_logger(__name__)


def run_discovery(
    db: Session,
    source: Source,
    adapter: SourceAdapter,
    marketplace_id: str,
    queries: list[str],
    estimated_sell_price_multiplier: Decimal = Decimal("1.8"),
) -> list[str]:
    """Search the given source for each query, link/create Products and
    SourceProducts, and evaluate a naive opportunity for each against the
    given marketplace (using a configurable sell-price multiplier as a
    stand-in until real marketplace price discovery is implemented).

    Returns the list of created Opportunity ids.
    """
    catalog = db.query(Product).all()
    created_opportunity_ids: list[str] = []

    for query in queries:
        for candidate in adapter.search_products(query):
            match = find_best_match(candidate.name, catalog)

            if match is not None:
                product = match.product
            else:
                product = Product(
                    sku=f"{source.name[:3].upper()}-{candidate.external_id}",
                    name=candidate.name,
                    category=None,
                    active=True,
                )
                db.add(product)
                db.commit()
                db.refresh(product)
                catalog.append(product)
                logger.info("Discovery created new product: %s", product.name)

            source_product = (
                db.query(SourceProduct)
                .filter_by(source_id=source.id, product_id=product.id)
                .first()
            )
            if source_product is None:
                source_product = SourceProduct(
                    source_id=source.id,
                    product_id=product.id,
                    external_id=candidate.external_id,
                    url=candidate.url,
                    current_price=candidate.price,
                    currency=candidate.currency,
                    stock_available=candidate.stock_available,
                )
                db.add(source_product)
                db.commit()
                db.refresh(source_product)
            else:
                source_product.current_price = candidate.price
                source_product.stock_available = candidate.stock_available
                db.add(source_product)
                db.commit()

            estimated_sell_price = (candidate.price * estimated_sell_price_multiplier).quantize(
                Decimal("0.01")
            )

            opportunity = evaluate_opportunity(
                db,
                OpportunityCreate(
                    product_id=product.id,
                    source_id=source.id,
                    marketplace_id=marketplace_id,
                    buy_price=float(candidate.price),
                    sell_price=float(estimated_sell_price),
                ),
            )
            created_opportunity_ids.append(opportunity.id)

    return created_opportunity_ids
