"""Arbitrage engine: orchestrates pricing + classification into a
persisted Opportunity record. This is the deterministic core of the
platform — AI enrichment (see ai_service) is layered on top afterwards.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.core.logging import get_logger
from backend.app.models.opportunity import Opportunity
from backend.app.schemas.opportunity import OpportunityCreate
from backend.app.services.opportunity_engine import classify_opportunity
from backend.app.services.pricing_engine import calculate_profit_breakdown

logger = get_logger(__name__)


def evaluate_opportunity(db: Session, inputs: OpportunityCreate) -> Opportunity:
    """Compute profitability for the given inputs, classify it, and
    persist it as a new Opportunity row."""
    breakdown = calculate_profit_breakdown(
        buy_price=inputs.buy_price,
        sell_price=inputs.sell_price,
        marketplace_fee=inputs.marketplace_fee,
        shipping_cost=inputs.shipping_cost,
        tax_cost=inputs.tax_cost,
        payment_cost=inputs.payment_cost,
        other_cost=inputs.other_cost,
    )
    status = classify_opportunity(breakdown, risk_score=None)

    opportunity = Opportunity(
        product_id=inputs.product_id,
        source_id=inputs.source_id,
        marketplace_id=inputs.marketplace_id,
        buy_price=breakdown.buy_price,
        sell_price=breakdown.sell_price,
        marketplace_fee=breakdown.marketplace_fee,
        shipping_cost=breakdown.shipping_cost,
        tax_cost=breakdown.tax_cost,
        payment_cost=breakdown.payment_cost,
        other_cost=breakdown.other_cost,
        gross_profit=breakdown.gross_profit,
        net_profit=breakdown.net_profit,
        roi=breakdown.roi,
        margin=breakdown.margin,
        status=status,
    )
    db.add(opportunity)
    db.commit()
    db.refresh(opportunity)

    logger.info(
        "Opportunity evaluated: product=%s roi=%s net_profit=%s status=%s",
        inputs.product_id,
        breakdown.roi,
        breakdown.net_profit,
        status.value,
    )
    return opportunity


def recompute_opportunity(db: Session, opportunity: Opportunity) -> Opportunity:
    """Recompute financials + classification for an existing Opportunity
    (e.g. after a source price change), preserving any AI scores already set."""
    breakdown = calculate_profit_breakdown(
        buy_price=opportunity.buy_price,
        sell_price=opportunity.sell_price,
        marketplace_fee=opportunity.marketplace_fee,
        shipping_cost=opportunity.shipping_cost,
        tax_cost=opportunity.tax_cost,
        payment_cost=opportunity.payment_cost,
        other_cost=opportunity.other_cost,
    )
    risk_score = float(opportunity.risk_score) if opportunity.risk_score is not None else None

    opportunity.gross_profit = breakdown.gross_profit
    opportunity.net_profit = breakdown.net_profit
    opportunity.roi = breakdown.roi
    opportunity.margin = breakdown.margin
    opportunity.status = classify_opportunity(breakdown, risk_score=risk_score)

    db.add(opportunity)
    db.commit()
    db.refresh(opportunity)
    return opportunity
