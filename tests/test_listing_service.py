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
        self.get_listing_result: MarketplaceListingInfo | None = None

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

    def get_listing(self, external_id) -> MarketplaceListingInfo | None:  # noqa: ANN001
        return self.get_listing_result


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


def test_refresh_listing_status_updates_from_the_real_current_state(
    db_session: Session, _product_and_marketplace: tuple[Product, Marketplace]
) -> None:
    """A freshly created item's status can be a transient value that
    resolves moments later (confirmed live 2026-09-22) — refresh must pull
    whatever the adapter reports right now, not trust the stored value."""
    product, marketplace = _product_and_marketplace
    adapter = _StubAdapter()
    record = listing_service.publish_and_record(
        db_session, adapter, product.id, marketplace.id, "Test Widget", Decimal("50000"), "COP"
    )
    assert record.status == ListingStatus.ACTIVE  # from create_listing's stub response

    adapter.get_listing_result = MarketplaceListingInfo(
        external_id="MCO999",
        title="Test Widget",
        price=Decimal("50000"),
        currency="COP",
        status="paused",
    )
    listing_service.refresh_listing_status(db_session, adapter, record)

    assert record.status == ListingStatus.PAUSED


def test_refresh_listing_status_is_a_noop_without_an_external_id(
    db_session: Session, _product_and_marketplace: tuple[Product, Marketplace]
) -> None:
    product, marketplace = _product_and_marketplace
    record = MarketplaceProduct(
        product_id=product.id,
        marketplace_id=marketplace.id,
        selling_price=Decimal("0"),
        status=ListingStatus.DRAFT,
    )
    adapter = _StubAdapter()

    result = listing_service.refresh_listing_status(db_session, adapter, record)

    assert result is record
    assert result.status == ListingStatus.DRAFT


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
