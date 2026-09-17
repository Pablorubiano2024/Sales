"""Seed the database with fictional demo data.

Populates a mock source, a marketplace (MercadoLibre/CO), five fictional
products, and a spread of arbitrage opportunities — profitable and
unprofitable, different ROIs, and different risk levels — so the
dashboard has something meaningful to show out of the box.

None of this is scraped or real; it is clearly-fictional seed/demo data.

Usage:
    python scripts/seed.py
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.database import SessionLocal, init_db  # noqa: E402
from backend.app.core.logging import get_logger  # noqa: E402
from backend.app.models.marketplace import Marketplace  # noqa: E402
from backend.app.models.product import Product  # noqa: E402
from backend.app.models.source import Source, SourceProduct, SourceType  # noqa: E402
from backend.app.schemas.opportunity import OpportunityCreate  # noqa: E402
from backend.app.services.arbitrage_engine import evaluate_opportunity  # noqa: E402
from backend.app.services.opportunity_engine import classify_opportunity  # noqa: E402
from backend.app.services.pricing_engine import calculate_profit_breakdown  # noqa: E402

logger = get_logger(__name__)

# (sku, name, category, buy_price, sell_price, marketplace_fee, shipping_cost,
#  payment_cost, synthetic_risk_score_or_None)
DEMO_PRODUCTS = [
    (
        "DEMO-001",
        "Wireless Bluetooth Headphones",
        "Electronics",
        Decimal("45000"),
        Decimal("120000"),
        Decimal("12000"),
        Decimal("8000"),
        Decimal("3000"),
        None,
    ),
    (
        "DEMO-002",
        "USB-C 7-in-1 Hub",
        "Electronics",
        Decimal("38000"),
        Decimal("85000"),
        Decimal("9000"),
        Decimal("7000"),
        Decimal("2000"),
        None,
    ),
    (
        "DEMO-003",
        "Adjustable Aluminum Laptop Stand",
        "Office",
        Decimal("32000"),
        Decimal("38000"),
        Decimal("6000"),
        Decimal("6000"),
        Decimal("1500"),
        None,
    ),
    (
        "DEMO-004",
        "LED Desk Lamp with Wireless Charger",
        "Home",
        Decimal("52000"),
        Decimal("150000"),
        Decimal("18000"),
        Decimal("9000"),
        Decimal("4000"),
        None,
    ),
    (
        "DEMO-005",
        "Portable Rechargeable Blender",
        "Home",
        Decimal("61000"),
        Decimal("130000"),
        Decimal("15000"),
        Decimal("9000"),
        Decimal("4000"),
        # Synthetic demo risk score to showcase REVIEW status — NOT from a
        # real Claude analysis (no ANTHROPIC_API_KEY call is made by this script).
        0.65,
    ),
]


def seed() -> None:
    init_db()
    db = SessionLocal()
    try:
        source = db.query(Source).filter_by(name="Demo Mock Supplier").first()
        if source is None:
            source = Source(
                name="Demo Mock Supplier",
                source_type=SourceType.MOCK,
                base_url="https://mock-supplier.example.com",
                country="CO",
            )
            db.add(source)
            db.commit()
            db.refresh(source)
            logger.info("Created source: %s", source.name)

        marketplace = db.query(Marketplace).filter_by(name="MercadoLibre Colombia").first()
        if marketplace is None:
            marketplace = Marketplace(name="MercadoLibre Colombia", country="CO")
            db.add(marketplace)
            db.commit()
            db.refresh(marketplace)
            logger.info("Created marketplace: %s", marketplace.name)

        for (
            sku,
            name,
            category,
            buy_price,
            sell_price,
            fee,
            shipping,
            payment,
            synthetic_risk,
        ) in DEMO_PRODUCTS:
            product = db.query(Product).filter_by(sku=sku).first()
            if product is None:
                product = Product(sku=sku, name=name, category=category)
                db.add(product)
                db.commit()
                db.refresh(product)
                logger.info("Created product: %s", product.name)

            source_product = (
                db.query(SourceProduct)
                .filter_by(source_id=source.id, product_id=product.id)
                .first()
            )
            if source_product is None:
                source_product = SourceProduct(
                    source_id=source.id,
                    product_id=product.id,
                    external_id=sku,
                    url=f"https://mock-supplier.example.com/products/{sku}",
                    current_price=buy_price,
                    currency="COP",
                    stock_available=True,
                )
                db.add(source_product)
                db.commit()

            opportunity = evaluate_opportunity(
                db,
                OpportunityCreate(
                    product_id=product.id,
                    source_id=source.id,
                    marketplace_id=marketplace.id,
                    buy_price=buy_price,
                    sell_price=sell_price,
                    marketplace_fee=fee,
                    shipping_cost=shipping,
                    payment_cost=payment,
                ),
            )

            if synthetic_risk is not None:
                breakdown = calculate_profit_breakdown(
                    buy_price=opportunity.buy_price,
                    sell_price=opportunity.sell_price,
                    marketplace_fee=opportunity.marketplace_fee,
                    shipping_cost=opportunity.shipping_cost,
                    tax_cost=opportunity.tax_cost,
                    payment_cost=opportunity.payment_cost,
                    other_cost=opportunity.other_cost,
                )
                opportunity.risk_score = synthetic_risk
                opportunity.status = classify_opportunity(breakdown, risk_score=synthetic_risk)
                db.add(opportunity)
                db.commit()

            logger.info(
                "Opportunity for %s: net_profit=%s roi=%s status=%s",
                product.name,
                opportunity.net_profit,
                opportunity.roi,
                opportunity.status.value,
            )

        print("Seed complete.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
