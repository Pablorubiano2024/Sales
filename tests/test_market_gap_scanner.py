"""Tests for market_gap_scanner.py — mocks catalog_lookup's two functions
directly (already unit-tested against real response shapes in
test_catalog_lookup.py) so these tests focus purely on the scan/compare/
persist logic."""

from __future__ import annotations

from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from backend.app.jobs import market_gap_scanner
from backend.app.models.market_gap import MarketGapEvent, MarketGapEventType, MarketGapSnapshot
from backend.app.models.marketplace import Marketplace
from backend.app.models.opportunity import Opportunity, OpportunityStatus
from backend.app.models.product import Product
from backend.app.models.source import Source, SourceType
from backend.app.services.catalog_lookup import BuyBoxSnapshot


def _make_opportunity(db: Session, name: str = "Apple iPhone 15") -> Opportunity:
    product = Product(sku=f"SCAN-{name}", name=name)
    source = Source(name="Test Source", source_type=SourceType.MOCK)
    marketplace = Marketplace(name="Test Marketplace")
    db.add_all([product, source, marketplace])
    db.commit()
    db.refresh(product)
    db.refresh(source)
    db.refresh(marketplace)

    opportunity = Opportunity(
        product_id=product.id,
        source_id=source.id,
        marketplace_id=marketplace.id,
        buy_price=Decimal("100000"),
        sell_price=Decimal("200000"),
        status=OpportunityStatus.APPROVED,
    )
    db.add(opportunity)
    db.commit()
    db.refresh(opportunity)
    return opportunity


def _dummy_client() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))


def test_scan_creates_first_snapshot_with_no_events(db_session: Session, monkeypatch) -> None:
    opportunity = _make_opportunity(db_session)
    monkeypatch.setattr(market_gap_scanner, "find_catalog_product", lambda *a, **k: "MCO27172667")
    monkeypatch.setattr(
        market_gap_scanner,
        "get_buy_box_snapshot",
        lambda *a, **k: BuyBoxSnapshot(
            seller_count=14,
            buy_box_price=Decimal("2528900"),
            buy_box_seller_id="1879808182",
            stock_available=True,
        ),
    )

    with _dummy_client() as client:
        result = market_gap_scanner.run_market_gap_scan(
            db_session, [opportunity], client=client, access_token="tok"
        )

    assert result.scanned == 1
    assert result.skipped_no_catalog_match == 0
    assert result.events_detected == 0
    snapshot = db_session.query(MarketGapSnapshot).filter_by(opportunity_id=opportunity.id).one()
    assert snapshot.catalog_product_id == "MCO27172667"
    assert snapshot.seller_count == 14


def test_scan_skips_when_no_catalog_match(db_session: Session, monkeypatch) -> None:
    opportunity = _make_opportunity(db_session)
    monkeypatch.setattr(market_gap_scanner, "find_catalog_product", lambda *a, **k: None)

    with _dummy_client() as client:
        result = market_gap_scanner.run_market_gap_scan(
            db_session, [opportunity], client=client, access_token="tok"
        )

    assert result.scanned == 0
    assert result.skipped_no_catalog_match == 1
    assert db_session.query(MarketGapSnapshot).count() == 0


def test_scan_reuses_catalog_product_id_from_previous_snapshot(
    db_session: Session, monkeypatch
) -> None:
    opportunity = _make_opportunity(db_session)
    db_session.add(
        MarketGapSnapshot(
            catalog_product_id="MCO27172667",
            opportunity_id=opportunity.id,
            seller_count=10,
            stock_available=True,
        )
    )
    db_session.commit()

    search_calls = []
    monkeypatch.setattr(
        market_gap_scanner,
        "find_catalog_product",
        lambda *a, **k: search_calls.append(1) or "SHOULD_NOT_BE_USED",
    )
    monkeypatch.setattr(
        market_gap_scanner,
        "get_buy_box_snapshot",
        lambda *a, **k: BuyBoxSnapshot(
            seller_count=10, buy_box_price=None, buy_box_seller_id=None, stock_available=True
        ),
    )

    with _dummy_client() as client:
        market_gap_scanner.run_market_gap_scan(
            db_session, [opportunity], client=client, access_token="tok"
        )

    assert search_calls == []  # never re-searched the catalog
    latest = (
        db_session.query(MarketGapSnapshot)
        .filter_by(opportunity_id=opportunity.id)
        .order_by(MarketGapSnapshot.captured_at.desc())
        .first()
    )
    assert latest.catalog_product_id == "MCO27172667"


def test_seller_count_dropped_event(db_session: Session, monkeypatch) -> None:
    opportunity = _make_opportunity(db_session)
    db_session.add(
        MarketGapSnapshot(
            catalog_product_id="MCO1",
            opportunity_id=opportunity.id,
            seller_count=14,
            buy_box_price=Decimal("2528900"),
            buy_box_seller_id="seller-1",
            stock_available=True,
        )
    )
    db_session.commit()

    monkeypatch.setattr(market_gap_scanner, "find_catalog_product", lambda *a, **k: "MCO1")
    monkeypatch.setattr(
        market_gap_scanner,
        "get_buy_box_snapshot",
        lambda *a, **k: BuyBoxSnapshot(
            seller_count=5,
            buy_box_price=Decimal("2528900"),
            buy_box_seller_id="seller-1",
            stock_available=True,
        ),
    )

    with _dummy_client() as client:
        result = market_gap_scanner.run_market_gap_scan(
            db_session, [opportunity], client=client, access_token="tok"
        )

    assert result.events_detected == 1
    event = db_session.query(MarketGapEvent).filter_by(opportunity_id=opportunity.id).one()
    assert event.event_type == MarketGapEventType.SELLER_COUNT_DROPPED


def test_buy_box_price_increased_event(db_session: Session, monkeypatch) -> None:
    opportunity = _make_opportunity(db_session)
    db_session.add(
        MarketGapSnapshot(
            catalog_product_id="MCO1",
            opportunity_id=opportunity.id,
            seller_count=5,
            buy_box_price=Decimal("100000"),
            buy_box_seller_id="seller-1",
            stock_available=True,
        )
    )
    db_session.commit()

    monkeypatch.setattr(market_gap_scanner, "find_catalog_product", lambda *a, **k: "MCO1")
    monkeypatch.setattr(
        market_gap_scanner,
        "get_buy_box_snapshot",
        lambda *a, **k: BuyBoxSnapshot(
            seller_count=5,
            buy_box_price=Decimal("120000"),
            buy_box_seller_id="seller-1",
            stock_available=True,
        ),
    )

    with _dummy_client() as client:
        result = market_gap_scanner.run_market_gap_scan(
            db_session, [opportunity], client=client, access_token="tok"
        )

    assert result.events_detected == 1
    event = db_session.query(MarketGapEvent).filter_by(opportunity_id=opportunity.id).one()
    assert event.event_type == MarketGapEventType.BUY_BOX_PRICE_INCREASED


def test_lowest_seller_disappeared_event(db_session: Session, monkeypatch) -> None:
    opportunity = _make_opportunity(db_session)
    db_session.add(
        MarketGapSnapshot(
            catalog_product_id="MCO1",
            opportunity_id=opportunity.id,
            seller_count=5,
            buy_box_price=Decimal("100000"),
            buy_box_seller_id="seller-1",
            stock_available=True,
        )
    )
    db_session.commit()

    monkeypatch.setattr(market_gap_scanner, "find_catalog_product", lambda *a, **k: "MCO1")
    monkeypatch.setattr(
        market_gap_scanner,
        "get_buy_box_snapshot",
        lambda *a, **k: BuyBoxSnapshot(
            seller_count=4,
            buy_box_price=Decimal("95000"),
            buy_box_seller_id="seller-2",
            stock_available=True,
        ),
    )

    with _dummy_client() as client:
        result = market_gap_scanner.run_market_gap_scan(
            db_session, [opportunity], client=client, access_token="tok"
        )

    event_types = {
        e.event_type
        for e in db_session.query(MarketGapEvent).filter_by(opportunity_id=opportunity.id).all()
    }
    assert MarketGapEventType.LOWEST_SELLER_DISAPPEARED in event_types
    assert MarketGapEventType.SELLER_COUNT_DROPPED in event_types
    assert result.events_detected == 2


def test_stock_recovered_event(db_session: Session, monkeypatch) -> None:
    opportunity = _make_opportunity(db_session)
    db_session.add(
        MarketGapSnapshot(
            catalog_product_id="MCO1",
            opportunity_id=opportunity.id,
            seller_count=0,
            buy_box_price=None,
            buy_box_seller_id=None,
            stock_available=False,
        )
    )
    db_session.commit()

    monkeypatch.setattr(market_gap_scanner, "find_catalog_product", lambda *a, **k: "MCO1")
    monkeypatch.setattr(
        market_gap_scanner,
        "get_buy_box_snapshot",
        lambda *a, **k: BuyBoxSnapshot(
            seller_count=1,
            buy_box_price=Decimal("50000"),
            buy_box_seller_id="seller-3",
            stock_available=True,
        ),
    )

    with _dummy_client() as client:
        result = market_gap_scanner.run_market_gap_scan(
            db_session, [opportunity], client=client, access_token="tok"
        )

    event_types = {
        e.event_type
        for e in db_session.query(MarketGapEvent).filter_by(opportunity_id=opportunity.id).all()
    }
    assert MarketGapEventType.STOCK_RECOVERED in event_types
    assert result.events_detected == 1


def test_skips_when_buy_box_fetch_fails(db_session: Session, monkeypatch) -> None:
    opportunity = _make_opportunity(db_session)
    monkeypatch.setattr(market_gap_scanner, "find_catalog_product", lambda *a, **k: "MCO1")
    monkeypatch.setattr(market_gap_scanner, "get_buy_box_snapshot", lambda *a, **k: None)

    with _dummy_client() as client:
        result = market_gap_scanner.run_market_gap_scan(
            db_session, [opportunity], client=client, access_token="tok"
        )

    assert result.scanned == 0
    assert result.skipped_no_catalog_match == 1
    assert db_session.query(MarketGapSnapshot).count() == 0
