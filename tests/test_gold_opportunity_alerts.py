"""Tests for gold_opportunity_alerts.py (Autopilot Phase 6)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.models.market_gap import MarketGapEvent, MarketGapEventType, MarketGapSnapshot
from backend.app.models.marketplace import Marketplace
from backend.app.models.opportunity import Opportunity, OpportunityStatus
from backend.app.models.product import Product
from backend.app.models.source import Source, SourceType
from backend.app.services.gold_opportunity_alerts import (
    format_gold_opportunity_message,
    maybe_alert_gold_opportunity,
)
from backend.app.services.pricing_engine import calculate_profit_breakdown


def _make_opportunity(
    db: Session, *, buy_price: Decimal = Decimal("100000"), sell_price: Decimal = Decimal("200000")
) -> Opportunity:
    product = Product(sku=f"GOLD-{buy_price}-{sell_price}", name="Gold Alert Test Product")
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


def _make_event(db: Session, opportunity: Opportunity) -> MarketGapEvent:
    snapshot = MarketGapSnapshot(
        catalog_product_id="MCO1",
        opportunity_id=opportunity.id,
        seller_count=2,
        buy_box_price=Decimal("199900"),
        stock_available=True,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)

    event = MarketGapEvent(
        catalog_product_id="MCO1",
        opportunity_id=opportunity.id,
        event_type=MarketGapEventType.SELLER_COUNT_DROPPED,
        current_snapshot_id=snapshot.id,
        detail="5 -> 2 vendedores",
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def test_format_message_includes_gold_opportunity_header(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    opportunity.confidence_score = 94
    event = _make_event(db_session, opportunity)

    message = format_gold_opportunity_message(opportunity, event)
    assert "🚨 *GOLD OPPORTUNITY*" in message
    assert "Gold Alert Test Product" in message
    assert "94%" in message
    assert "5 -> 2 vendedores" in message


def test_maybe_alert_sends_when_thresholds_clear(db_session: Session, monkeypatch) -> None:
    # High margin (50%), and no real competition/sales/stability data yet
    # so the score comes from margin+recency alone — force it high enough
    # by monkeypatching score_opportunity isn't needed since real margin
    # of 50% + recency already clears 90 in this pure/fresh scenario is
    # unlikely, so directly stub the scoring step instead of relying on
    # incidental point totals.
    opportunity = _make_opportunity(
        db_session, buy_price=Decimal("100000"), sell_price=Decimal("300000")
    )
    event = _make_event(db_session, opportunity)

    def fake_score_opportunity(db, opp):
        opp.confidence_score = 95
        db.commit()
        db.refresh(opp)
        return opp

    sent = {}

    def fake_send_slack(text: str) -> bool:
        sent["text"] = text
        return True

    monkeypatch.setattr(
        "backend.app.services.gold_opportunity_alerts.score_opportunity", fake_score_opportunity
    )
    monkeypatch.setattr("backend.app.services.gold_opportunity_alerts.send_slack", fake_send_slack)

    result = maybe_alert_gold_opportunity(db_session, opportunity, event)
    assert result is True
    assert "GOLD OPPORTUNITY" in sent["text"]


def test_maybe_alert_skips_when_score_below_threshold(db_session: Session, monkeypatch) -> None:
    opportunity = _make_opportunity(
        db_session, buy_price=Decimal("100000"), sell_price=Decimal("300000")
    )
    event = _make_event(db_session, opportunity)

    def fake_score_opportunity(db, opp):
        opp.confidence_score = 50
        db.commit()
        db.refresh(opp)
        return opp

    called = {"sent": False}
    monkeypatch.setattr(
        "backend.app.services.gold_opportunity_alerts.score_opportunity", fake_score_opportunity
    )
    monkeypatch.setattr(
        "backend.app.services.gold_opportunity_alerts.send_slack",
        lambda text: called.__setitem__("sent", True),
    )

    result = maybe_alert_gold_opportunity(db_session, opportunity, event)
    assert result is False
    assert called["sent"] is False


def test_maybe_alert_skips_when_margin_below_threshold(db_session: Session, monkeypatch) -> None:
    # Low margin: buy 100000, sell 110000 -> well under 25%.
    opportunity = _make_opportunity(
        db_session, buy_price=Decimal("100000"), sell_price=Decimal("110000")
    )
    event = _make_event(db_session, opportunity)

    def fake_score_opportunity(db, opp):
        opp.confidence_score = 95
        db.commit()
        db.refresh(opp)
        return opp

    called = {"sent": False}
    monkeypatch.setattr(
        "backend.app.services.gold_opportunity_alerts.score_opportunity", fake_score_opportunity
    )
    monkeypatch.setattr(
        "backend.app.services.gold_opportunity_alerts.send_slack",
        lambda text: called.__setitem__("sent", True),
    )

    result = maybe_alert_gold_opportunity(db_session, opportunity, event)
    assert result is False
    assert called["sent"] is False
