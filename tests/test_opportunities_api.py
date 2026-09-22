from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.marketplace import Marketplace
from backend.app.models.product import Product
from backend.app.models.source import Source, SourceProduct, SourceType


def _seed(db: Session) -> dict:
    product = Product(sku="SRC-1", name="Widget")
    source = Source(name="Test Source", source_type=SourceType.MOCK)
    marketplace = Marketplace(name="Test Marketplace")
    db.add_all([product, source, marketplace])
    db.commit()
    db.refresh(product)
    db.refresh(source)
    db.refresh(marketplace)

    source_product = SourceProduct(
        source_id=source.id,
        product_id=product.id,
        external_id="ext-1",
        url="https://example.com/widget",
        current_price=10000,
        currency="COP",
    )
    db.add(source_product)
    db.commit()
    return {"product": product, "source": source, "marketplace": marketplace}


def test_list_opportunities_includes_source_url(client: TestClient, db_session: Session) -> None:
    seeded = _seed(db_session)

    create = client.post(
        "/api/opportunities/analyze",
        json={
            "inputs": {
                "product_id": seeded["product"].id,
                "source_id": seeded["source"].id,
                "marketplace_id": seeded["marketplace"].id,
                "buy_price": 45000,
                "sell_price": 120000,
                "marketplace_fee": 12000,
                "shipping_cost": 8000,
                "payment_cost": 3000,
            },
            "use_ai": False,
        },
    )
    assert create.status_code == 200
    assert create.json()["source_url"] == "https://example.com/widget"

    list_response = client.get("/api/opportunities")
    assert list_response.status_code == 200
    body = list_response.json()
    assert len(body) == 1
    assert body[0]["source_url"] == "https://example.com/widget"

    get_response = client.get(f"/api/opportunities/{body[0]['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["source_url"] == "https://example.com/widget"


def test_opportunity_source_url_is_none_without_a_matching_source_product(
    client: TestClient, db_session: Session
) -> None:
    product = Product(sku="NO-SRC", name="No Source Widget")
    source = Source(name="Test Source 2", source_type=SourceType.MOCK)
    marketplace = Marketplace(name="Test Marketplace 2")
    db_session.add_all([product, source, marketplace])
    db_session.commit()
    db_session.refresh(product)
    db_session.refresh(source)
    db_session.refresh(marketplace)

    create = client.post(
        "/api/opportunities/analyze",
        json={
            "inputs": {
                "product_id": product.id,
                "source_id": source.id,
                "marketplace_id": marketplace.id,
                "buy_price": 45000,
                "sell_price": 120000,
            },
            "use_ai": False,
        },
    )
    assert create.status_code == 200
    assert create.json()["source_url"] is None
