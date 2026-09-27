"""Basic persistence/relationship tests for the Autopilot Phase 0 models
(lifecycle, market gap, listing draft, analytics) — confirms the schema
is sound (defaults, FKs, relationships) before any service logic is
built on top of it."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.models.analytics import AnalyticsEvent, AnalyticsEventType
from backend.app.models.lifecycle import LifecycleStage, OpportunityLifecycleEvent
from backend.app.models.listing_draft import ListingDraft, ListingDraftStatus
from backend.app.models.market_gap import MarketGapEvent, MarketGapEventType, MarketGapSnapshot
from backend.app.models.marketplace import Marketplace
from backend.app.models.opportunity import Opportunity, OpportunityStatus
from backend.app.models.product import Product
from backend.app.models.source import Source, SourceType


def _make_opportunity(db: Session) -> Opportunity:
    product = Product(sku="AUTO-1", name="Autopilot Test Product")
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


def test_opportunity_defaults_to_found_lifecycle_stage(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    assert opportunity.lifecycle_stage == LifecycleStage.FOUND
    assert opportunity.confidence_score is None


def test_lifecycle_event_links_back_to_its_opportunity(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    event = OpportunityLifecycleEvent(
        opportunity_id=opportunity.id,
        stage=LifecycleStage.VALIDATED,
        reason="Passed opportunity_validator checks",
    )
    db_session.add(event)
    db_session.commit()
    db_session.refresh(opportunity)

    assert len(opportunity.lifecycle_events) == 1
    assert opportunity.lifecycle_events[0].stage == LifecycleStage.VALIDATED


def test_market_gap_snapshot_and_event_persist(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    previous = MarketGapSnapshot(
        catalog_product_id="MCO123",
        opportunity_id=opportunity.id,
        seller_count=5,
        buy_box_price=Decimal("199900"),
        stock_available=True,
    )
    current = MarketGapSnapshot(
        catalog_product_id="MCO123",
        opportunity_id=opportunity.id,
        seller_count=3,
        buy_box_price=Decimal("219900"),
        stock_available=True,
    )
    db_session.add_all([previous, current])
    db_session.commit()
    db_session.refresh(previous)
    db_session.refresh(current)

    event = MarketGapEvent(
        catalog_product_id="MCO123",
        opportunity_id=opportunity.id,
        event_type=MarketGapEventType.SELLER_COUNT_DROPPED,
        previous_snapshot_id=previous.id,
        current_snapshot_id=current.id,
        detail="5 -> 3 sellers",
    )
    db_session.add(event)
    db_session.commit()

    stored = db_session.query(MarketGapEvent).filter_by(catalog_product_id="MCO123").one()
    assert stored.event_type == MarketGapEventType.SELLER_COUNT_DROPPED
    assert stored.previous_snapshot_id == previous.id


def test_listing_draft_defaults_to_draft_status(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    draft = ListingDraft(
        opportunity_id=opportunity.id,
        title="Freidora De Aire Holstein 9 Litros",
        price=Decimal("899900"),
    )
    db_session.add(draft)
    db_session.commit()
    db_session.refresh(draft)

    assert draft.status == ListingDraftStatus.DRAFT
    assert draft.opportunity.id == opportunity.id


def test_analytics_event_persists_denormalized_margins(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    event = AnalyticsEvent(
        opportunity_id=opportunity.id,
        event_type=AnalyticsEventType.SOLD,
        estimated_margin=Decimal("0.28"),
        real_margin=Decimal("0.24"),
        time_to_sale_minutes=4320,
        confidence_score_at_detection=94,
    )
    db_session.add(event)
    db_session.commit()

    stored = db_session.query(AnalyticsEvent).filter_by(opportunity_id=opportunity.id).one()
    assert stored.event_type == AnalyticsEventType.SOLD
    assert stored.real_margin == Decimal("0.24")
    assert stored.confidence_score_at_detection == 94
