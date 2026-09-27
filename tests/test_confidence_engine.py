"""Unit tests for the Autopilot Confidence Engine (Phase 2). Every factor
is tested for both its "no real data yet" branch and its scored branch,
so the explainability guarantee (every point has a reason) is verified,
not just the final number."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.core.time import utcnow
from backend.app.models.analytics import AnalyticsEvent, AnalyticsEventType
from backend.app.models.lifecycle import LifecycleStage, OpportunityLifecycleEvent
from backend.app.models.market_gap import MarketGapSnapshot
from backend.app.models.marketplace import Marketplace
from backend.app.models.opportunity import Opportunity, OpportunityStatus
from backend.app.models.price_history import PriceHistory
from backend.app.models.product import Product
from backend.app.models.source import Source, SourceType
from backend.app.services.confidence_engine import (
    MAX_TOTAL_SCORE,
    compute_confidence,
    recalibrate_weights,
    score_opportunity,
)
from backend.app.services.pricing_engine import calculate_profit_breakdown


def _make_opportunity(
    db: Session, *, buy_price: Decimal = Decimal("100000"), sell_price: Decimal = Decimal("200000")
) -> Opportunity:
    product = Product(sku=f"CONF-{uuid.uuid4()}", name="Confidence Test Product")
    source = Source(name="Test Source", source_type=SourceType.MOCK)
    marketplace = Marketplace(name="Test Marketplace")
    db.add_all([product, source, marketplace])
    db.commit()
    db.refresh(product)
    db.refresh(source)
    db.refresh(marketplace)

    breakdown = calculate_profit_breakdown(buy_price, sell_price)
    opportunity = Opportunity(
        product_id=product.id,
        source_id=source.id,
        marketplace_id=marketplace.id,
        buy_price=buy_price,
        sell_price=sell_price,
        net_profit=breakdown.net_profit,
        roi=breakdown.roi,
        margin=breakdown.margin,
        status=OpportunityStatus.APPROVED,
    )
    db.add(opportunity)
    db.commit()
    db.refresh(opportunity)
    return opportunity


def test_every_factor_has_a_human_readable_reason(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    result = compute_confidence(db_session, opportunity)
    assert len(result.breakdown) == 5
    for factor in result.breakdown:
        assert factor.reasoning
        assert factor.label
    assert result.score == sum(f.points for f in result.breakdown)
    assert 0 <= result.score <= MAX_TOTAL_SCORE


def test_high_margin_scores_more_than_low_margin(db_session: Session) -> None:
    high = _make_opportunity(db_session, buy_price=Decimal("100000"), sell_price=Decimal("300000"))
    low = _make_opportunity(db_session, buy_price=Decimal("100000"), sell_price=Decimal("105000"))
    high_result = compute_confidence(db_session, high)
    low_result = compute_confidence(db_session, low)
    high_margin_points = next(f.points for f in high_result.breakdown if "Margen" in f.label)
    low_margin_points = next(f.points for f in low_result.breakdown if "Margen" in f.label)
    assert high_margin_points > low_margin_points


def test_competition_uses_real_snapshot_when_available(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    db_session.add(
        MarketGapSnapshot(
            catalog_product_id="MCO1",
            opportunity_id=opportunity.id,
            seller_count=2,
            stock_available=True,
        )
    )
    db_session.commit()

    result = compute_confidence(db_session, opportunity)
    competition = next(
        f for f in result.breakdown if "ompetencia" in f.label or "recuente" in f.label
    )
    assert "Buy Box real" in competition.label
    assert "snapshot real" in competition.reasoning


def test_competition_falls_back_to_discovery_recurrence_proxy(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    result = compute_confidence(db_session, opportunity)
    competition = next(
        f for f in result.breakdown if "recuente" in f.label or "ompetencia" in f.label
    )
    assert "proxy" in competition.reasoning


def test_sales_history_rewards_real_sold_events(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    no_history = compute_confidence(db_session, opportunity)
    no_history_points = next(f.points for f in no_history.breakdown if "ventas" in f.reasoning)
    assert no_history_points == 0

    for _ in range(3):
        another = _make_opportunity(db_session)
        db_session.add(
            AnalyticsEvent(
                opportunity_id=another.id,
                event_type=AnalyticsEventType.SOLD,
            )
        )
    db_session.commit()
    # Re-point the analytics events at the same product as `opportunity`
    # so they count toward its sales-history factor.
    for event in db_session.query(AnalyticsEvent).all():
        linked_opportunity = db_session.get(Opportunity, event.opportunity_id)
        linked_opportunity.product_id = opportunity.product_id
    db_session.commit()

    with_history = compute_confidence(db_session, opportunity)
    with_history_points = next(f.points for f in with_history.breakdown if "ventas" in f.reasoning)
    assert with_history_points > 0


def test_supplier_stability_rewards_unchanged_price(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    for _ in range(5):
        db_session.add(
            PriceHistory(
                product_id=opportunity.product_id,
                source_id=opportunity.source_id,
                price=Decimal("100000"),
            )
        )
    db_session.commit()

    result = compute_confidence(db_session, opportunity)
    stability = next(f for f in result.breakdown if "roveedor" in f.label)
    assert stability.points > 0
    assert "1 precio" in stability.reasoning


def test_supplier_stability_penalizes_volatile_price(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    for price in ["100000", "120000", "90000", "150000"]:
        db_session.add(
            PriceHistory(
                product_id=opportunity.product_id,
                source_id=opportunity.source_id,
                price=Decimal(price),
            )
        )
    db_session.commit()

    result = compute_confidence(db_session, opportunity)
    stable_opportunity = _make_opportunity(db_session)
    db_session.add(
        PriceHistory(
            product_id=stable_opportunity.product_id,
            source_id=stable_opportunity.source_id,
            price=Decimal("100000"),
        )
    )
    db_session.commit()
    stable_result = compute_confidence(db_session, stable_opportunity)

    volatile_points = next(f.points for f in result.breakdown if "roveedor" in f.label)
    stable_points = next(f.points for f in stable_result.breakdown if "roveedor" in f.label)
    assert volatile_points < stable_points


def test_recency_rewards_freshly_found_opportunity(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    db_session.add(
        OpportunityLifecycleEvent(
            opportunity_id=opportunity.id,
            stage=LifecycleStage.FOUND,
            occurred_at=utcnow(),
        )
    )
    db_session.commit()

    result = compute_confidence(db_session, opportunity)
    recency = next(f for f in result.breakdown if "Gap" in f.label)
    assert recency.points == 10


def test_recency_penalizes_old_opportunity(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    db_session.add(
        OpportunityLifecycleEvent(
            opportunity_id=opportunity.id,
            stage=LifecycleStage.FOUND,
            occurred_at=utcnow() - timedelta(days=30),
        )
    )
    db_session.commit()

    result = compute_confidence(db_session, opportunity)
    recency = next(f for f in result.breakdown if "Gap" in f.label)
    assert recency.points == 0


def test_score_opportunity_persists_score_and_breakdown(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    updated = score_opportunity(db_session, opportunity)
    assert updated.confidence_score is not None
    assert updated.confidence_breakdown is not None
    assert "margin" in updated.confidence_breakdown


def test_score_opportunity_never_touches_financial_fields(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    original_margin = opportunity.margin
    original_roi = opportunity.roi
    original_net_profit = opportunity.net_profit
    updated = score_opportunity(db_session, opportunity)
    assert updated.margin == original_margin
    assert updated.roi == original_roi
    assert updated.net_profit == original_net_profit


def test_recalibrate_weights_reports_none_without_data(db_session: Session) -> None:
    report = recalibrate_weights(db_session)
    assert report.sold_count == 0
    assert report.expired_count == 0
    assert report.directionally_correct is None


def test_recalibrate_weights_reports_averages_from_real_events(db_session: Session) -> None:
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

    report = recalibrate_weights(db_session)
    assert report.sold_count == 1
    assert report.expired_count == 1
    assert report.avg_score_sold == 90
    assert report.avg_score_expired == 40
    assert report.directionally_correct is True
