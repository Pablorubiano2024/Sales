"""Tests for opportunity classification and the arbitrage engine orchestration."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.models.marketplace import Marketplace
from backend.app.models.opportunity import OpportunityStatus
from backend.app.models.product import Product
from backend.app.models.source import Source, SourceType
from backend.app.schemas.opportunity import OpportunityCreate
from backend.app.services.arbitrage_engine import evaluate_opportunity
from backend.app.services.opportunity_engine import classify_opportunity
from backend.app.services.pricing_engine import calculate_profit_breakdown

TEST_SETTINGS = Settings(
    min_roi=Decimal("0.30"),
    min_net_profit=Decimal("20000"),
    max_risk_score=0.50,
    anthropic_api_key=None,
)


def test_classify_rejected_when_net_profit_negative() -> None:
    breakdown = calculate_profit_breakdown(
        buy_price=32000, sell_price=38000, marketplace_fee=6000, shipping_cost=6000
    )
    assert classify_opportunity(breakdown, settings=TEST_SETTINGS) == OpportunityStatus.REJECTED


def test_classify_rejected_when_below_thresholds() -> None:
    breakdown = calculate_profit_breakdown(buy_price=100000, sell_price=110000)
    assert classify_opportunity(breakdown, settings=TEST_SETTINGS) == OpportunityStatus.REJECTED


def test_classify_promising_when_above_minimums_but_not_comfortable() -> None:
    breakdown = calculate_profit_breakdown(
        buy_price=38000,
        sell_price=85000,
        marketplace_fee=9000,
        shipping_cost=7000,
        payment_cost=2000,
    )
    assert classify_opportunity(breakdown, settings=TEST_SETTINGS) == OpportunityStatus.PROMISING


def test_classify_approved_when_comfortably_above_thresholds() -> None:
    breakdown = calculate_profit_breakdown(
        buy_price=45000,
        sell_price=120000,
        marketplace_fee=12000,
        shipping_cost=8000,
        payment_cost=3000,
    )
    assert classify_opportunity(breakdown, settings=TEST_SETTINGS) == OpportunityStatus.APPROVED


def test_classify_review_when_risk_too_high() -> None:
    breakdown = calculate_profit_breakdown(
        buy_price=61000,
        sell_price=130000,
        marketplace_fee=15000,
        shipping_cost=9000,
        payment_cost=4000,
    )
    assert (
        classify_opportunity(breakdown, risk_score=0.65, settings=TEST_SETTINGS)
        == OpportunityStatus.REVIEW
    )


def _make_product_source_marketplace(db: Session) -> tuple[Product, Source, Marketplace]:
    product = Product(sku="TEST-001", name="Test Widget")
    source = Source(name="Test Source", source_type=SourceType.MOCK)
    marketplace = Marketplace(name="Test Marketplace")
    db.add_all([product, source, marketplace])
    db.commit()
    db.refresh(product)
    db.refresh(source)
    db.refresh(marketplace)
    return product, source, marketplace


def test_evaluate_opportunity_persists_deterministic_result(db_session: Session) -> None:
    product, source, marketplace = _make_product_source_marketplace(db_session)

    opportunity = evaluate_opportunity(
        db_session,
        OpportunityCreate(
            product_id=product.id,
            source_id=source.id,
            marketplace_id=marketplace.id,
            buy_price=45000,
            sell_price=120000,
            marketplace_fee=12000,
            shipping_cost=8000,
            payment_cost=3000,
        ),
    )

    assert opportunity.id is not None
    assert float(opportunity.net_profit) == 52000.0
    assert opportunity.status == OpportunityStatus.APPROVED
