"""Unit tests for the Opportunity Validator (Autopilot Phase 1). Pure
rule checks — only `seller_count` touches the DB (a MarketGapSnapshot
lookup), everything else is evaluated straight off an Opportunity."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.models.market_gap import MarketGapSnapshot
from backend.app.models.marketplace import Marketplace
from backend.app.models.opportunity import Opportunity, OpportunityStatus
from backend.app.models.product import Product
from backend.app.models.source import Source, SourceType
from backend.app.services.opportunity_validator import validate_opportunity
from backend.app.services.pricing_engine import calculate_profit_breakdown


def _make_opportunity(
    db: Session, *, buy_price: Decimal, sell_price: Decimal, confidence_score: int | None = None
) -> Opportunity:
    product = Product(sku="VAL-1", name="Validator Test Product")
    source = Source(name="Test Source", source_type=SourceType.MOCK)
    marketplace = Marketplace(name="Test Marketplace")
    db.add_all([product, source, marketplace])
    db.commit()
    db.refresh(product)
    db.refresh(source)
    db.refresh(marketplace)

    # margin/roi/net_profit are stored columns (not derived properties) —
    # compute them the same way real discovery does, via pricing_engine,
    # so the validator is exercised against realistic values.
    breakdown = calculate_profit_breakdown(buy_price, sell_price)

    opportunity = Opportunity(
        product_id=product.id,
        source_id=source.id,
        marketplace_id=marketplace.id,
        buy_price=buy_price,
        sell_price=sell_price,
        net_profit=breakdown.net_profit,
        roi=breakdown.roi,
        margin=breakdown.margin,
        status=OpportunityStatus.APPROVED,
        confidence_score=confidence_score,
    )
    db.add(opportunity)
    db.commit()
    db.refresh(opportunity)
    return opportunity


def test_high_margin_opportunity_passes_the_margin_check(db_session: Session) -> None:
    opportunity = _make_opportunity(
        db_session, buy_price=Decimal("100000"), sell_price=Decimal("200000")
    )
    result = validate_opportunity(db_session, opportunity)
    margin_check = next(c for c in result.checks if c.name == "margin")
    assert margin_check.passed is True


def test_low_margin_opportunity_fails_the_margin_check_and_overall(db_session: Session) -> None:
    opportunity = _make_opportunity(
        db_session, buy_price=Decimal("100000"), sell_price=Decimal("105000")
    )
    result = validate_opportunity(db_session, opportunity)
    margin_check = next(c for c in result.checks if c.name == "margin")
    assert margin_check.passed is False
    assert result.overall_passed is False
    assert margin_check in result.failed_checks


def test_missing_confidence_score_is_not_applicable_not_a_failure(db_session: Session) -> None:
    opportunity = _make_opportunity(
        db_session, buy_price=Decimal("100000"), sell_price=Decimal("200000")
    )
    result = validate_opportunity(db_session, opportunity)
    score_check = next(c for c in result.checks if c.name == "score")
    assert score_check.passed is None
    assert result.overall_passed is True


def test_confidence_score_below_threshold_fails(db_session: Session) -> None:
    opportunity = _make_opportunity(
        db_session, buy_price=Decimal("100000"), sell_price=Decimal("200000"), confidence_score=80
    )
    result = validate_opportunity(db_session, opportunity)
    score_check = next(c for c in result.checks if c.name == "score")
    assert score_check.passed is False
    assert result.overall_passed is False


def test_confidence_score_at_or_above_threshold_passes(db_session: Session) -> None:
    opportunity = _make_opportunity(
        db_session, buy_price=Decimal("100000"), sell_price=Decimal("200000"), confidence_score=94
    )
    result = validate_opportunity(db_session, opportunity)
    score_check = next(c for c in result.checks if c.name == "score")
    assert score_check.passed is True


def test_seller_count_without_snapshot_is_not_applicable(db_session: Session) -> None:
    opportunity = _make_opportunity(
        db_session, buy_price=Decimal("100000"), sell_price=Decimal("200000")
    )
    result = validate_opportunity(db_session, opportunity)
    seller_check = next(c for c in result.checks if c.name == "seller_count")
    assert seller_check.passed is None


def test_seller_count_uses_latest_snapshot(db_session: Session) -> None:
    opportunity = _make_opportunity(
        db_session, buy_price=Decimal("100000"), sell_price=Decimal("200000")
    )
    old = MarketGapSnapshot(
        catalog_product_id="MCO1",
        opportunity_id=opportunity.id,
        seller_count=5,
        stock_available=True,
    )
    db_session.add(old)
    db_session.commit()
    new = MarketGapSnapshot(
        catalog_product_id="MCO1",
        opportunity_id=opportunity.id,
        seller_count=20,
        stock_available=True,
    )
    db_session.add(new)
    db_session.commit()

    result = validate_opportunity(db_session, opportunity)
    seller_check = next(c for c in result.checks if c.name == "seller_count")
    assert seller_check.passed is False
    assert "20" in seller_check.detail


def test_stock_none_is_not_applicable(db_session: Session) -> None:
    opportunity = _make_opportunity(
        db_session, buy_price=Decimal("100000"), sell_price=Decimal("200000")
    )
    result = validate_opportunity(db_session, opportunity, live_stock_available=None)
    stock_check = next(c for c in result.checks if c.name == "stock")
    assert stock_check.passed is None


def test_stock_unavailable_fails(db_session: Session) -> None:
    opportunity = _make_opportunity(
        db_session, buy_price=Decimal("100000"), sell_price=Decimal("200000")
    )
    result = validate_opportunity(db_session, opportunity, live_stock_available=False)
    stock_check = next(c for c in result.checks if c.name == "stock")
    assert stock_check.passed is False
    assert result.overall_passed is False


def test_price_drift_within_tolerance_passes(db_session: Session) -> None:
    opportunity = _make_opportunity(
        db_session, buy_price=Decimal("100000"), sell_price=Decimal("200000")
    )
    result = validate_opportunity(db_session, opportunity, live_price_cop=Decimal("100500"))
    price_check = next(c for c in result.checks if c.name == "price_unchanged")
    assert price_check.passed is True


def test_price_drift_beyond_tolerance_fails(db_session: Session) -> None:
    opportunity = _make_opportunity(
        db_session, buy_price=Decimal("100000"), sell_price=Decimal("200000")
    )
    result = validate_opportunity(db_session, opportunity, live_price_cop=Decimal("115000"))
    price_check = next(c for c in result.checks if c.name == "price_unchanged")
    assert price_check.passed is False
    assert result.overall_passed is False


def test_supplier_reputation_always_not_applicable(db_session: Session) -> None:
    opportunity = _make_opportunity(
        db_session, buy_price=Decimal("100000"), sell_price=Decimal("200000")
    )
    result = validate_opportunity(db_session, opportunity)
    reputation_check = next(c for c in result.checks if c.name == "supplier_reputation")
    assert reputation_check.passed is None


def test_fully_passing_opportunity_is_overall_passed(db_session: Session) -> None:
    opportunity = _make_opportunity(
        db_session, buy_price=Decimal("100000"), sell_price=Decimal("200000"), confidence_score=95
    )
    result = validate_opportunity(
        db_session, opportunity, live_stock_available=True, live_price_cop=Decimal("100000")
    )
    assert result.overall_passed is True
    assert result.failed_checks == []
