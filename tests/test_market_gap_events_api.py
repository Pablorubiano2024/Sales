"""API test for GET /api/market-gap-events (Autopilot Phase 7)."""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.market_gap import MarketGapEvent, MarketGapEventType, MarketGapSnapshot
from backend.app.models.marketplace import Marketplace
from backend.app.models.opportunity import Opportunity, OpportunityStatus
from backend.app.models.product import Product
from backend.app.models.source import Source, SourceType


def test_list_market_gap_events_empty(client: TestClient) -> None:
    response = client.get("/api/market-gap-events")
    assert response.status_code == 200
    assert response.json() == []


def test_list_market_gap_events_includes_product_name(
    client: TestClient, db_session: Session
) -> None:
    product = Product(sku="MGE-1", name="Widget")
    source = Source(name="Test Source", source_type=SourceType.MOCK)
    marketplace = Marketplace(name="Test Marketplace")
    db_session.add_all([product, source, marketplace])
    db_session.commit()
    db_session.refresh(product)
    db_session.refresh(source)
    db_session.refresh(marketplace)

    opportunity = Opportunity(
        product_id=product.id,
        source_id=source.id,
        marketplace_id=marketplace.id,
        buy_price=Decimal("100000"),
        sell_price=Decimal("200000"),
        status=OpportunityStatus.APPROVED,
    )
    db_session.add(opportunity)
    db_session.commit()
    db_session.refresh(opportunity)

    snapshot = MarketGapSnapshot(
        catalog_product_id="MCO1",
        opportunity_id=opportunity.id,
        seller_count=3,
        stock_available=True,
    )
    db_session.add(snapshot)
    db_session.commit()
    db_session.refresh(snapshot)

    event = MarketGapEvent(
        catalog_product_id="MCO1",
        opportunity_id=opportunity.id,
        event_type=MarketGapEventType.SELLER_COUNT_DROPPED,
        current_snapshot_id=snapshot.id,
        detail="5 -> 3 vendedores",
    )
    db_session.add(event)
    db_session.commit()

    response = client.get("/api/market-gap-events")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["product_name"] == "Widget"
    assert body[0]["event_type"] == "seller_count_dropped"
    assert body[0]["detail"] == "5 -> 3 vendedores"
