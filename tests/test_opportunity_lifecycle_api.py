"""API tests for GET /api/opportunities/{id}/lifecycle (Autopilot Phase 7)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.marketplace import Marketplace
from backend.app.models.product import Product
from backend.app.models.source import Source, SourceType


def test_lifecycle_returns_404_for_missing_opportunity(client: TestClient) -> None:
    response = client.get("/api/opportunities/does-not-exist/lifecycle")
    assert response.status_code == 404


def test_lifecycle_includes_the_real_found_event(client: TestClient, db_session: Session) -> None:
    product = Product(sku="LIFE-1", name="Widget")
    source = Source(name="Test Source", source_type=SourceType.MOCK)
    marketplace = Marketplace(name="Test Marketplace")
    db_session.add_all([product, source, marketplace])
    db_session.commit()
    db_session.refresh(product)
    db_session.refresh(source)
    db_session.refresh(marketplace)

    # /analyze's underlying evaluate_opportunity() records a real FOUND
    # lifecycle event the first time this (product, source, marketplace)
    # combo is created — see arbitrage_engine.py.
    create = client.post(
        "/api/opportunities/analyze",
        json={
            "inputs": {
                "product_id": product.id,
                "source_id": source.id,
                "marketplace_id": marketplace.id,
                "buy_price": 100000,
                "sell_price": 200000,
            },
            "use_ai": False,
        },
    )
    assert create.status_code == 200
    opportunity_id = create.json()["id"]

    response = client.get(f"/api/opportunities/{opportunity_id}/lifecycle")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["stage"] == "found"
