"""Tests for listing_service.py — connecting a real create_listing() result
to a persisted MarketplaceProduct row (and the pause/price-update actions
the daily sync job needs) via a lightweight stub adapter, not a real
network call."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from backend.app.integrations.base import MarketplaceListingInfo
from backend.app.models.marketplace import ListingStatus, Marketplace, MarketplaceProduct
from backend.app.models.product import Product
from backend.app.services import listing_service


class _StubAdapter:
    """Records calls instead of hitting the real MercadoLibre API."""

    def __init__(self) -> None:
        self.create_calls: list[dict] = []
        self.update_calls: list[dict] = []
        self.price_calls: list[tuple[str, Decimal]] = []

    def create_listing(
        self, product_id, title, price, currency, **kwargs
    ) -> MarketplaceListingInfo:  # noqa: ANN001
        self.create_calls.append(
            {"product_id": product_id, "title": title, "price": price, **kwargs}
        )
        return MarketplaceListingInfo(
            external_id="MCO999",
            title=title,
            price=price,
            currency=currency,
            status="active",
            url="https://articulo.mercadolibre.com.co/MCO-999",
        )

    def update_listing(self, external_id, **fields) -> MarketplaceListingInfo:  # noqa: ANN001
        self.update_calls.append({"external_id": external_id, **fields})
        return MarketplaceListingInfo(
            external_id=external_id,
            title="whatever",
            price=Decimal("0"),
            currency="COP",
            status=fields.get("status", "active"),
        )

    def update_price(self, external_id, price) -> None:  # noqa: ANN001
        self.price_calls.append((external_id, price))


@pytest.fixture()
def _product_and_marketplace(db_session: Session) -> tuple[Product, Marketplace]:
    product = Product(sku="TEST-1", name="Test Widget")
    marketplace = Marketplace(name="MercadoLibre Colombia")
    db_session.add_all([product, marketplace])
    db_session.commit()
    db_session.refresh(product)
    db_session.refresh(marketplace)
    return product, marketplace


def test_publish_and_record_creates_a_new_marketplace_product(
    db_session: Session, _product_and_marketplace: tuple[Product, Marketplace]
) -> None:
    product, marketplace = _product_and_marketplace
    adapter = _StubAdapter()

    record = listing_service.publish_and_record(
        db_session,
        adapter,  # type: ignore[arg-type]
        product.id,
        marketplace.id,
        title="Test Widget",
        price=Decimal("50000"),
        currency="COP",
        category_id="MCO123",
    )

    assert record.external_id == "MCO999"
    assert record.status == ListingStatus.ACTIVE
    assert record.selling_price == Decimal("50000")
    assert adapter.create_calls[0]["category_id"] == "MCO123"


def test_publish_and_record_updates_existing_row_instead_of_duplicating(
    db_session: Session, _product_and_marketplace: tuple[Product, Marketplace]
) -> None:
    product, marketplace = _product_and_marketplace
    adapter = _StubAdapter()

    listing_service.publish_and_record(
        db_session, adapter, product.id, marketplace.id, "Test Widget", Decimal("50000"), "COP"
    )
    listing_service.publish_and_record(
        db_session, adapter, product.id, marketplace.id, "Test Widget", Decimal("60000"), "COP"
    )

    rows = (
        db_session.query(MarketplaceProduct)
        .filter_by(product_id=product.id, marketplace_id=marketplace.id)
        .all()
    )
    assert len(rows) == 1
    assert rows[0].selling_price == Decimal("60000")


def test_pause_listing_calls_update_listing_and_persists_status(
    db_session: Session, _product_and_marketplace: tuple[Product, Marketplace]
) -> None:
    product, marketplace = _product_and_marketplace
    adapter = _StubAdapter()
    record = listing_service.publish_and_record(
        db_session, adapter, product.id, marketplace.id, "Test Widget", Decimal("50000"), "COP"
    )

    listing_service.pause_listing(db_session, adapter, record, reason="out of stock")

    assert record.status == ListingStatus.PAUSED
    assert adapter.update_calls == [{"external_id": "MCO999", "status": "paused"}]


def test_pause_listing_is_a_noop_when_already_paused(
    db_session: Session, _product_and_marketplace: tuple[Product, Marketplace]
) -> None:
    product, marketplace = _product_and_marketplace
    adapter = _StubAdapter()
    record = listing_service.publish_and_record(
        db_session, adapter, product.id, marketplace.id, "Test Widget", Decimal("50000"), "COP"
    )
    listing_service.pause_listing(db_session, adapter, record, reason="first pause")
    adapter.update_calls.clear()

    listing_service.pause_listing(db_session, adapter, record, reason="second call")

    assert adapter.update_calls == []


def test_update_listing_price_calls_adapter_and_persists(
    db_session: Session, _product_and_marketplace: tuple[Product, Marketplace]
) -> None:
    product, marketplace = _product_and_marketplace
    adapter = _StubAdapter()
    record = listing_service.publish_and_record(
        db_session, adapter, product.id, marketplace.id, "Test Widget", Decimal("50000"), "COP"
    )

    listing_service.update_listing_price(db_session, adapter, record, Decimal("75000"))

    assert record.selling_price == Decimal("75000")
    assert adapter.price_calls == [("MCO999", Decimal("75000"))]
