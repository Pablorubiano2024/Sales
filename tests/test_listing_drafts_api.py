"""API tests for /api/listing-drafts (Autopilot Phase 3)."""

from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.models.listing_draft import ListingDraft, ListingDraftStatus
from backend.app.models.marketplace import Marketplace
from backend.app.models.opportunity import Opportunity, OpportunityStatus
from backend.app.models.product import Product
from backend.app.models.source import Source, SourceType


def _make_opportunity(db: Session) -> Opportunity:
    product = Product(sku="LD-API-1", name="Widget")
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


def test_list_drafts_empty_by_default(client: TestClient) -> None:
    response = client.get("/api/listing-drafts")
    assert response.status_code == 200
    assert response.json() == []


def test_generate_returns_404_for_missing_opportunity(client: TestClient) -> None:
    response = client.post("/api/listing-drafts/generate/does-not-exist")
    assert response.status_code == 404


def test_generate_returns_422_for_unsupported_source(
    client: TestClient, db_session: Session
) -> None:
    """The seeded "Test Source" has no real adapter in SUPPORTED_SOURCES."""
    opportunity = _make_opportunity(db_session)
    response = client.post(f"/api/listing-drafts/generate/{opportunity.id}")
    assert response.status_code == 422
    assert "no soportada" in response.json()["detail"]


def test_approve_and_reject_transitions(client: TestClient, db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    draft = ListingDraft(
        opportunity_id=opportunity.id,
        title="Widget",
        price=Decimal("200000"),
    )
    db_session.add(draft)
    db_session.commit()
    db_session.refresh(draft)

    approve_response = client.post(f"/api/listing-drafts/{draft.id}/approve")
    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == ListingDraftStatus.READY.value

    reject_response = client.post(
        f"/api/listing-drafts/{draft.id}/reject", json={"reason": "precio desactualizado"}
    )
    assert reject_response.status_code == 200
    body = reject_response.json()
    assert body["status"] == ListingDraftStatus.REJECTED.value
    assert body["rejection_reason"] == "precio desactualizado"


def test_approve_returns_404_for_missing_draft(client: TestClient) -> None:
    response = client.post("/api/listing-drafts/does-not-exist/approve")
    assert response.status_code == 404


def test_reject_returns_404_for_missing_draft(client: TestClient) -> None:
    response = client.post("/api/listing-drafts/does-not-exist/reject", json={"reason": "x"})
    assert response.status_code == 404


def test_list_drafts_filters_by_status(client: TestClient, db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    draft = ListingDraft(opportunity_id=opportunity.id, title="Widget", price=Decimal("200000"))
    db_session.add(draft)
    db_session.commit()

    draft_status_response = client.get("/api/listing-drafts", params={"status_filter": "ready"})
    assert draft_status_response.status_code == 200
    assert draft_status_response.json() == []

    all_response = client.get("/api/listing-drafts", params={"status_filter": "draft"})
    assert all_response.status_code == 200
    assert len(all_response.json()) == 1
