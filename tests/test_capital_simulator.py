"""Tests for capital_simulator.py (Autopilot Phase 7)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.models.analytics import AnalyticsEvent, AnalyticsEventType
from backend.app.models.marketplace import Marketplace
from backend.app.models.opportunity import Opportunity, OpportunityStatus
from backend.app.models.product import Product
from backend.app.models.source import Source, SourceType
from backend.app.services.capital_simulator import (
    DEFAULT_TIME_TO_SALE_DAYS,
    CapitalSimulationResult,
    SimulationError,
    run_capital_simulation,
)


def _make_opportunity(
    db: Session,
    *,
    buy_price: Decimal,
    margin: Decimal,
    net_profit: Decimal,
    status: OpportunityStatus = OpportunityStatus.APPROVED,
) -> Opportunity:
    product = Product(sku=f"SIM-{uuid.uuid4()}", name="Capital Sim Test Product")
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
        buy_price=buy_price,
        sell_price=buy_price * 2,
        margin=margin,
        net_profit=net_profit,
        status=status,
    )
    db.add(opportunity)
    db.commit()
    db.refresh(opportunity)
    return opportunity


def test_returns_error_for_non_positive_capital(db_session: Session) -> None:
    result = run_capital_simulation(
        db_session, capital=Decimal("0"), max_daily_purchases=5, min_margin=Decimal("0.20")
    )
    assert isinstance(result, SimulationError)


def test_returns_error_for_non_positive_max_daily_purchases(db_session: Session) -> None:
    result = run_capital_simulation(
        db_session, capital=Decimal("1000000"), max_daily_purchases=0, min_margin=Decimal("0.20")
    )
    assert isinstance(result, SimulationError)


def test_returns_error_when_no_qualifying_opportunities(db_session: Session) -> None:
    _make_opportunity(
        db_session, buy_price=Decimal("100000"), margin=Decimal("0.10"), net_profit=Decimal("10000")
    )
    result = run_capital_simulation(
        db_session,
        capital=Decimal("1000000"),
        max_daily_purchases=5,
        min_margin=Decimal("0.20"),
    )
    assert isinstance(result, SimulationError)


def test_ignores_non_approved_opportunities(db_session: Session) -> None:
    _make_opportunity(
        db_session,
        buy_price=Decimal("100000"),
        margin=Decimal("0.30"),
        net_profit=Decimal("30000"),
        status=OpportunityStatus.PROMISING,
    )
    result = run_capital_simulation(
        db_session,
        capital=Decimal("1000000"),
        max_daily_purchases=5,
        min_margin=Decimal("0.20"),
    )
    assert isinstance(result, SimulationError)


def test_uses_default_time_to_sale_without_real_sales_data(db_session: Session) -> None:
    _make_opportunity(
        db_session, buy_price=Decimal("100000"), margin=Decimal("0.30"), net_profit=Decimal("30000")
    )
    result = run_capital_simulation(
        db_session,
        capital=Decimal("1000000"),
        max_daily_purchases=5,
        min_margin=Decimal("0.20"),
    )
    assert isinstance(result, CapitalSimulationResult)
    assert result.time_to_sale_is_real_data is False
    assert result.avg_time_to_sale_days == DEFAULT_TIME_TO_SALE_DAYS


def test_uses_real_time_to_sale_when_analytics_events_exist(db_session: Session) -> None:
    opportunity = _make_opportunity(
        db_session, buy_price=Decimal("100000"), margin=Decimal("0.30"), net_profit=Decimal("30000")
    )
    db_session.add_all(
        [
            AnalyticsEvent(
                opportunity_id=opportunity.id,
                event_type=AnalyticsEventType.SOLD,
                time_to_sale_minutes=1440 * 3,  # 3 days
            ),
            AnalyticsEvent(
                opportunity_id=opportunity.id,
                event_type=AnalyticsEventType.SOLD,
                time_to_sale_minutes=1440 * 5,  # 5 days
            ),
        ]
    )
    db_session.commit()

    result = run_capital_simulation(
        db_session,
        capital=Decimal("1000000"),
        max_daily_purchases=5,
        min_margin=Decimal("0.20"),
    )
    assert isinstance(result, CapitalSimulationResult)
    assert result.time_to_sale_is_real_data is True
    assert result.avg_time_to_sale_days == Decimal("4.0000")  # (3+5)/2


def test_daily_purchases_capped_by_max_daily_purchases(db_session: Session) -> None:
    _make_opportunity(
        db_session, buy_price=Decimal("10000"), margin=Decimal("0.30"), net_profit=Decimal("3000")
    )
    # Huge capital + short rotation would otherwise sustain far more than
    # the user's requested max.
    opportunity = _make_opportunity(
        db_session, buy_price=Decimal("10000"), margin=Decimal("0.30"), net_profit=Decimal("3000")
    )
    db_session.add(
        AnalyticsEvent(
            opportunity_id=opportunity.id,
            event_type=AnalyticsEventType.SOLD,
            time_to_sale_minutes=1,  # ~instant rotation
        )
    )
    db_session.commit()

    result = run_capital_simulation(
        db_session,
        capital=Decimal("100000000"),
        max_daily_purchases=3,
        min_margin=Decimal("0.20"),
    )
    assert isinstance(result, CapitalSimulationResult)
    assert result.daily_purchases == 3


def test_daily_purchases_is_a_continuous_rate_not_floored(db_session: Session) -> None:
    """Real bug found live 2026-09-28: flooring the purchase count to a
    whole number produced a false "$0 monthly profit" for real capital
    that genuinely supports periodic (not daily) purchases — e.g. capital
    only covering 2 units at a time against a 7-day rotation is a real,
    profitable "buy 2, wait a week" cadence, not a dead scenario."""
    _make_opportunity(
        db_session, buy_price=Decimal("100000"), margin=Decimal("0.30"), net_profit=Decimal("30000")
    )
    result = run_capital_simulation(
        db_session,
        capital=Decimal("250000"),  # only enough for 2 units at a time
        max_daily_purchases=100,
        min_margin=Decimal("0.20"),
    )
    assert isinstance(result, CapitalSimulationResult)
    # 2 units capacity / 7 default days => a fractional but real rate.
    assert result.daily_purchases == Decimal("0.2857")
    assert result.monthly_profit > Decimal("0.00")
    assert result.days_to_double_capital is not None


def test_monthly_projection_math(db_session: Session) -> None:
    opportunity = _make_opportunity(
        db_session, buy_price=Decimal("100000"), margin=Decimal("0.30"), net_profit=Decimal("30000")
    )
    db_session.add(
        AnalyticsEvent(
            opportunity_id=opportunity.id,
            event_type=AnalyticsEventType.SOLD,
            time_to_sale_minutes=1440,  # 1 day rotation
        )
    )
    db_session.commit()

    result = run_capital_simulation(
        db_session,
        capital=Decimal("1000000"),  # 10 units capacity
        max_daily_purchases=10,
        min_margin=Decimal("0.20"),
    )
    assert isinstance(result, CapitalSimulationResult)
    assert result.avg_time_to_sale_days == Decimal("1.0000")
    assert result.daily_purchases == 10
    assert result.daily_profit == Decimal("300000.00")
    assert result.monthly_profit == Decimal("9000000.00")
    assert result.monthly_roi == Decimal("9.0000")
    assert result.days_to_double_capital == Decimal("3.33")
