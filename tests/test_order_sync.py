"""Tests for order_sync.py — mocks the adapter's get_orders() directly
(already unit-tested against a real-shaped response in
test_mercadolibre.py) so these focus on the map-to-internal-Order logic."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from backend.app.integrations.base import MarketplaceOrderInfo
from backend.app.jobs.order_sync import run_order_sync
from backend.app.models.marketplace import Marketplace, MarketplaceProduct
from backend.app.models.opportunity import Opportunity, OpportunityStatus
from backend.app.models.order import Order
from backend.app.models.product import Product
from backend.app.models.source import Source, SourceType


def _make_listing(db: Session, *, external_id: str) -> MarketplaceProduct:
    product = Product(sku=f"SYNC-{external_id}", name="Order Sync Test Product")
    marketplace = Marketplace(name="MercadoLibre Colombia")
    db.add_all([product, marketplace])
    db.commit()
    db.refresh(product)
    db.refresh(marketplace)

    listing = MarketplaceProduct(
        product_id=product.id,
        marketplace_id=marketplace.id,
        external_id=external_id,
        selling_price=Decimal("200000"),
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def test_run_order_sync_creates_order_for_known_listing(db_session: Session) -> None:
    listing = _make_listing(db_session, external_id="MCO123")
    adapter = MagicMock()
    adapter.get_orders.return_value = [
        MarketplaceOrderInfo(
            external_id="ML-1",
            status="paid",
            total_amount=Decimal("200000"),
            currency="COP",
            item_external_id="MCO123",
            quantity=1,
        )
    ]

    created = run_order_sync(db_session, adapter)

    assert created == 1
    order = db_session.query(Order).filter_by(marketplace_order_id="ML-1").one()
    assert order.product_id == listing.product_id


def test_run_order_sync_skips_unknown_listing(db_session: Session) -> None:
    adapter = MagicMock()
    adapter.get_orders.return_value = [
        MarketplaceOrderInfo(
            external_id="ML-2",
            status="paid",
            total_amount=Decimal("100000"),
            currency="COP",
            item_external_id="MCO-UNKNOWN",
            quantity=1,
        )
    ]

    created = run_order_sync(db_session, adapter)

    assert created == 0
    assert db_session.query(Order).count() == 0


def test_run_order_sync_skips_order_without_item(db_session: Session) -> None:
    adapter = MagicMock()
    adapter.get_orders.return_value = [
        MarketplaceOrderInfo(
            external_id="ML-3",
            status="paid",
            total_amount=Decimal("100000"),
            currency="COP",
            item_external_id=None,
        )
    ]

    created = run_order_sync(db_session, adapter)

    assert created == 0


def test_run_order_sync_does_not_duplicate_existing_orders(db_session: Session) -> None:
    listing = _make_listing(db_session, external_id="MCO123")
    order = Order(
        marketplace_order_id="ML-1",
        product_id=listing.product_id,
        selling_price=Decimal("200000"),
        supplier_price=Decimal("100000"),
    )
    db_session.add(order)
    db_session.commit()

    adapter = MagicMock()
    adapter.get_orders.return_value = [
        MarketplaceOrderInfo(
            external_id="ML-1",
            status="paid",
            total_amount=Decimal("200000"),
            currency="COP",
            item_external_id="MCO123",
            quantity=1,
        )
    ]

    created = run_order_sync(db_session, adapter)

    assert created == 0
    assert db_session.query(Order).count() == 1


def test_run_order_sync_resolves_and_links_the_real_opportunity(db_session: Session) -> None:
    listing = _make_listing(db_session, external_id="MCO123")
    source = Source(name="Falabella", source_type=SourceType.MOCK)
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)

    opportunity = Opportunity(
        product_id=listing.product_id,
        source_id=source.id,
        marketplace_id=listing.marketplace_id,
        buy_price=Decimal("100000"),
        sell_price=Decimal("200000"),
        status=OpportunityStatus.APPROVED,
    )
    db_session.add(opportunity)
    db_session.commit()

    adapter = MagicMock()
    adapter.get_orders.return_value = [
        MarketplaceOrderInfo(
            external_id="ML-4",
            status="paid",
            total_amount=Decimal("200000"),
            currency="COP",
            item_external_id="MCO123",
            quantity=1,
        )
    ]

    run_order_sync(db_session, adapter)

    order = db_session.query(Order).filter_by(marketplace_order_id="ML-4").one()
    assert order.opportunity_id == opportunity.id
