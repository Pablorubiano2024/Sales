"""API tests for GET /api/opportunities/{id}/validate (Autopilot Phase 1)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.marketplace import Marketplace
from backend.app.models.product import Product
from backend.app.models.source import Source, SourceType


def _create_opportunity(client: TestClient, db: Session, **overrides: object) -> str:
    product = Product(sku="VAL-API-1", name="Widget")
    source = Source(name="Test Source", source_type=SourceType.MOCK)
    marketplace = Marketplace(name="Test Marketplace")
    db.add_all([product, source, marketplace])
    db.commit()
    db.refresh(product)
    db.refresh(source)
    db.refresh(marketplace)

    payload = {
        "product_id": product.id,
        "source_id": source.id,
        "marketplace_id": marketplace.id,
        "buy_price": 100000,
        "sell_price": 200000,
    }
    payload.update(overrides)
    response = client.post("/api/opportunities/analyze", json={"inputs": payload, "use_ai": False})
    assert response.status_code == 200
    return str(response.json()["id"])


def test_validate_returns_404_for_missing_opportunity(client: TestClient) -> None:
    response = client.get("/api/opportunities/does-not-exist/validate")
    assert response.status_code == 404


def test_validate_reports_stock_pending_and_score_evaluated_without_refresh(
    client: TestClient, db_session: Session
) -> None:
    opportunity_id = _create_opportunity(client, db_session)

    response = client.get(f"/api/opportunities/{opportunity_id}/validate")
    assert response.status_code == 200
    body = response.json()

    margin_check = next(c for c in body["checks"] if c["name"] == "margin")
    assert margin_check["passed"] is True

    stock_check = next(c for c in body["checks"] if c["name"] == "stock")
    assert stock_check["passed"] is None  # not checked — refresh_live wasn't set

    # /analyze always runs the Confidence Engine (Phase 2), so the score
    # check is actually evaluated here (not "pending") — a brand-new test
    # opportunity with no real sales/competition history won't clear the
    # >=90 bar, so overall_passed correctly comes back False.
    score_check = next(c for c in body["checks"] if c["name"] == "score")
    assert score_check["passed"] is False
    assert body["overall_passed"] is False


def test_validate_with_refresh_live_reports_unsupported_source_as_stock_failure(
    client: TestClient, db_session: Session
) -> None:
    """The seeded "Test Source" has no real adapter in SUPPORTED_SOURCES —
    refresh_live=True should surface that as a failed stock check rather
    than silently skip it or crash."""
    opportunity_id = _create_opportunity(client, db_session)

    response = client.get(f"/api/opportunities/{opportunity_id}/validate?refresh_live=true")
    assert response.status_code == 200
    body = response.json()

    stock_check = next(c for c in body["checks"] if c["name"] == "stock")
    assert stock_check["passed"] is False
    assert body["overall_passed"] is False


def test_validate_fails_overall_when_margin_too_low(
    client: TestClient, db_session: Session
) -> None:
    opportunity_id = _create_opportunity(client, db_session, buy_price=100000, sell_price=105000)

    response = client.get(f"/api/opportunities/{opportunity_id}/validate")
    assert response.status_code == 200
    body = response.json()
    assert body["overall_passed"] is False
