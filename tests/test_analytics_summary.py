"""Tests for analytics_summary.py (Autopilot Phase 7)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.models.analytics import AnalyticsEvent, AnalyticsEventType
from backend.app.models.marketplace import Marketplace
from backend.app.models.opportunity import Opportunity, OpportunityStatus
from backend.app.models.product import Product
from backend.app.models.source import Source, SourceType
from backend.app.services.analytics_summary import get_analytics_summary


def _make_opportunity(db: Session) -> Opportunity:
    product = Product(sku="AS-1", name="Analytics Summary Test Product")
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


def test_summary_with_no_events_is_all_zero_or_none(db_session: Session) -> None:
    summary = get_analytics_summary(db_session)
    assert summary.detected_count == 0
    assert summary.published_count == 0
    assert summary.sold_count == 0
    assert summary.expired_count == 0
    assert summary.avg_time_to_sale_days is None
    assert summary.avg_estimated_margin is None
    assert summary.avg_real_margin is None


def test_summary_counts_each_event_type(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    db_session.add_all(
        [
            AnalyticsEvent(opportunity_id=opportunity.id, event_type=AnalyticsEventType.DETECTED),
            AnalyticsEvent(opportunity_id=opportunity.id, event_type=AnalyticsEventType.PUBLISHED),
            AnalyticsEvent(opportunity_id=opportunity.id, event_type=AnalyticsEventType.SOLD),
            AnalyticsEvent(opportunity_id=opportunity.id, event_type=AnalyticsEventType.EXPIRED),
        ]
    )
    db_session.commit()

    summary = get_analytics_summary(db_session)
    assert summary.detected_count == 1
    assert summary.published_count == 1
    assert summary.sold_count == 1
    assert summary.expired_count == 1


def test_summary_computes_real_averages_from_sold_events(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    db_session.add_all(
        [
            AnalyticsEvent(
                opportunity_id=opportunity.id,
                event_type=AnalyticsEventType.SOLD,
                estimated_margin=Decimal("0.30"),
                real_margin=Decimal("0.25"),
                time_to_sale_minutes=1440 * 2,  # 2 days
            ),
            AnalyticsEvent(
                opportunity_id=opportunity.id,
                event_type=AnalyticsEventType.SOLD,
                estimated_margin=Decimal("0.40"),
                real_margin=Decimal("0.35"),
                time_to_sale_minutes=1440 * 4,  # 4 days
            ),
        ]
    )
    db_session.commit()

    summary = get_analytics_summary(db_session)
    assert summary.sold_count == 2
    assert summary.avg_time_to_sale_days == 3.0
    assert summary.avg_estimated_margin == 0.35
    assert summary.avg_real_margin == 0.30


def test_summary_includes_confidence_recalibration_report(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    db_session.add_all(
        [
            AnalyticsEvent(
                opportunity_id=opportunity.id,
                event_type=AnalyticsEventType.SOLD,
                confidence_score_at_detection=90,
            ),
            AnalyticsEvent(
                opportunity_id=opportunity.id,
                event_type=AnalyticsEventType.EXPIRED,
                confidence_score_at_detection=40,
            ),
        ]
    )
    db_session.commit()

    summary = get_analytics_summary(db_session)
    assert summary.confidence_recalibration.directionally_correct is True
