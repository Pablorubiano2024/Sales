"""Tests for order_router.py (Autopilot Phase 5, Sandbox mode) — pure DB
logic, no MercadoLibre calls."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.core.time import utcnow
from backend.app.models.analytics import AnalyticsEvent, AnalyticsEventType
from backend.app.models.lifecycle import LifecycleStage, OpportunityLifecycleEvent
from backend.app.models.marketplace import Marketplace
from backend.app.models.opportunity import Opportunity, OpportunityStatus
from backend.app.models.order import OrderStatus
from backend.app.models.product import Product
from backend.app.models.source import Source, SourceProduct, SourceType
from backend.app.services.order_router import create_order_from_sale, select_best_supplier


def _make_product(db: Session) -> Product:
    product = Product(sku="ORD-1", name="Order Router Test Product")
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


def _make_opportunity(
    db: Session, product: Product, *, confidence_score: int | None = None
) -> Opportunity:
    source = Source(name="Falabella", source_type=SourceType.MOCK)
    marketplace = Marketplace(name="MercadoLibre Colombia")
    db.add_all([source, marketplace])
    db.commit()
    db.refresh(source)
    db.refresh(marketplace)

    opportunity = Opportunity(
        product_id=product.id,
        source_id=source.id,
        marketplace_id=marketplace.id,
        buy_price=Decimal("100000"),
        sell_price=Decimal("200000"),
        margin=Decimal("0.30"),
        status=OpportunityStatus.APPROVED,
        confidence_score=confidence_score,
    )
    db.add(opportunity)
    db.commit()
    db.refresh(opportunity)
    return opportunity


def _make_source_product(
    db: Session, product: Product, *, source_name: str, price: Decimal, stock: bool = True
) -> SourceProduct:
    source = Source(name=source_name, source_type=SourceType.MOCK)
    db.add(source)
    db.commit()
    db.refresh(source)

    sp = SourceProduct(
        source_id=source.id, product_id=product.id, current_price=price, stock_available=stock
    )
    db.add(sp)
    db.commit()
    db.refresh(sp)
    return sp


def test_select_best_supplier_returns_none_without_stock(db_session: Session) -> None:
    product = _make_product(db_session)
    _make_source_product(
        db_session, product, source_name="Out of stock", price=Decimal("10000"), stock=False
    )
    assert select_best_supplier(db_session, product.id) is None


def test_select_best_supplier_picks_cheapest_in_stock(db_session: Session) -> None:
    product = _make_product(db_session)
    _make_source_product(db_session, product, source_name="Expensive", price=Decimal("50000"))
    cheap = _make_source_product(db_session, product, source_name="Cheap", price=Decimal("30000"))
    _make_source_product(
        db_session,
        product,
        source_name="Cheapest but no stock",
        price=Decimal("10000"),
        stock=False,
    )

    choice = select_best_supplier(db_session, product.id)
    assert choice is not None
    assert choice.source_product.id == cheap.id
    assert choice.source.name == "Cheap"


def test_create_order_from_sale_picks_supplier_and_computes_profit(db_session: Session) -> None:
    product = _make_product(db_session)
    _make_source_product(db_session, product, source_name="Falabella", price=Decimal("100000"))

    order = create_order_from_sale(
        db_session,
        product_id=product.id,
        selling_price=Decimal("200000"),
        marketplace_order_id="ML-ORDER-1",
        marketplace_fees=Decimal("20000"),
        shipping_cost=Decimal("10000"),
    )

    assert order.status == OrderStatus.NEW
    assert order.supplier_price == Decimal("100000")
    assert order.expected_profit == Decimal("70000.00")
    assert order.marketplace_order_id == "ML-ORDER-1"


def test_create_order_from_sale_without_stock_is_awaiting_supplier_purchase(
    db_session: Session,
) -> None:
    product = _make_product(db_session)

    order = create_order_from_sale(
        db_session, product_id=product.id, selling_price=Decimal("200000")
    )

    assert order.status == OrderStatus.AWAITING_SUPPLIER_PURCHASE
    assert order.supplier_price == Decimal("0")


def test_create_order_from_sale_is_idempotent_on_marketplace_order_id(db_session: Session) -> None:
    product = _make_product(db_session)
    _make_source_product(db_session, product, source_name="Falabella", price=Decimal("100000"))

    first = create_order_from_sale(
        db_session,
        product_id=product.id,
        selling_price=Decimal("200000"),
        marketplace_order_id="ML-ORDER-DUP",
    )
    second = create_order_from_sale(
        db_session,
        product_id=product.id,
        selling_price=Decimal("999999"),  # would produce a different order if not deduped
        marketplace_order_id="ML-ORDER-DUP",
    )

    assert first.id == second.id
    assert second.selling_price == Decimal("200000.00")


def test_create_order_from_sale_without_opportunity_id_records_no_analytics(
    db_session: Session,
) -> None:
    product = _make_product(db_session)
    _make_source_product(db_session, product, source_name="Falabella", price=Decimal("100000"))

    create_order_from_sale(db_session, product_id=product.id, selling_price=Decimal("200000"))

    assert db_session.query(AnalyticsEvent).count() == 0
    assert db_session.query(OpportunityLifecycleEvent).count() == 0


def test_create_order_from_sale_records_sold_analytics_with_real_margin(
    db_session: Session,
) -> None:
    product = _make_product(db_session)
    _make_source_product(db_session, product, source_name="Falabella", price=Decimal("100000"))
    opportunity = _make_opportunity(db_session, product, confidence_score=94)

    create_order_from_sale(
        db_session,
        product_id=product.id,
        selling_price=Decimal("200000"),
        opportunity_id=opportunity.id,
    )

    event = (
        db_session.query(AnalyticsEvent)
        .filter_by(opportunity_id=opportunity.id, event_type=AnalyticsEventType.SOLD)
        .one()
    )
    assert event.real_margin == Decimal("0.5000")  # (200000-100000)/200000
    assert event.estimated_margin == Decimal("0.3000")
    assert event.confidence_score_at_detection == 94
    assert event.time_to_sale_minutes is None  # no real FOUND event exists

    db_session.refresh(opportunity)
    assert opportunity.lifecycle_stage == LifecycleStage.SOLD


def test_create_order_from_sale_computes_real_time_to_sale_from_found_event(
    db_session: Session,
) -> None:
    product = _make_product(db_session)
    _make_source_product(db_session, product, source_name="Falabella", price=Decimal("100000"))
    opportunity = _make_opportunity(db_session, product)
    db_session.add(
        OpportunityLifecycleEvent(
            opportunity_id=opportunity.id,
            stage=LifecycleStage.FOUND,
            occurred_at=utcnow() - timedelta(days=2),
        )
    )
    db_session.commit()

    create_order_from_sale(
        db_session,
        product_id=product.id,
        selling_price=Decimal("200000"),
        opportunity_id=opportunity.id,
    )

    event = (
        db_session.query(AnalyticsEvent)
        .filter_by(opportunity_id=opportunity.id, event_type=AnalyticsEventType.SOLD)
        .one()
    )
    assert event.time_to_sale_minutes is not None
    assert 2870 <= event.time_to_sale_minutes <= 2890  # ~2 days, small test-runtime slack
