"""API tests for POST /api/capital-simulation (Autopilot Phase 7)."""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.marketplace import Marketplace
from backend.app.models.opportunity import Opportunity, OpportunityStatus
from backend.app.models.product import Product
from backend.app.models.source import Source, SourceType


def _make_opportunity(db: Session) -> Opportunity:
    product = Product(sku="CAPI-1", name="Widget")
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
        margin=Decimal("0.30"),
        net_profit=Decimal("30000"),
        status=OpportunityStatus.APPROVED,
    )
    db.add(opportunity)
    db.commit()
    return opportunity


def test_simulate_returns_422_for_no_qualifying_opportunities(client: TestClient) -> None:
    response = client.post(
        "/api/capital-simulation",
        json={"capital": 1000000, "max_daily_purchases": 5, "min_margin": 0.20},
    )
    assert response.status_code == 422


def test_simulate_returns_real_projection(client: TestClient, db_session: Session) -> None:
    _make_opportunity(db_session)

    response = client.post(
        "/api/capital-simulation",
        json={"capital": 1000000, "max_daily_purchases": 5, "min_margin": 0.20},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["qualifying_opportunities"] == 1
    assert body["time_to_sale_is_real_data"] is False
    assert body["monthly_profit"] >= 0


def test_simulate_rejects_non_positive_capital(client: TestClient) -> None:
    response = client.post(
        "/api/capital-simulation",
        json={"capital": 0, "max_daily_purchases": 5, "min_margin": 0.20},
    )
    assert response.status_code == 422
