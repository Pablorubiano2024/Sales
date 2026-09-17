"""AI enrichment service.

Orchestrates calling Claude to enrich an Opportunity with qualitative
scores, and persists the result. AI analysis is enrichment only: it never
changes buy/sell price, costs, gross/net profit, ROI or margin — those
stay exactly as computed by the deterministic pricing/opportunity engines.
If AI analysis is unavailable or fails, the opportunity keeps its
mathematically-derived status untouched.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from backend.app.core.logging import get_logger
from backend.app.integrations.claude import get_claude_service
from backend.app.models.opportunity import Opportunity
from backend.app.services.opportunity_engine import classify_opportunity
from backend.app.services.pricing_engine import calculate_profit_breakdown

logger = get_logger(__name__)


def enrich_opportunity_with_ai(db: Session, opportunity: Opportunity) -> Opportunity:
    """Call Claude for qualitative scoring and merge results onto the
    opportunity. Re-classifies status using the (now known) risk score,
    but never touches the financial figures themselves."""
    claude = get_claude_service()

    product_name = opportunity.product.name if opportunity.product else "Unknown product"
    category = opportunity.product.category if opportunity.product else None

    analysis_input = {
        "product_name": product_name,
        "category": category,
        "buy_price": float(opportunity.buy_price),
        "sell_price": float(opportunity.sell_price),
        "roi": float(opportunity.roi),
        "margin": float(opportunity.margin),
        "stock_available": True,
    }

    result = claude.analyze_opportunity(analysis_input)
    if result is None:
        logger.info("AI enrichment unavailable for opportunity %s; leaving as-is.", opportunity.id)
        return opportunity

    opportunity.competition_score = result.competition_score
    opportunity.demand_score = result.demand_score
    opportunity.risk_score = result.risk_score
    opportunity.ai_score = result.overall_score
    opportunity.ai_analysis = json.dumps(
        {
            "recommendation": result.recommendation,
            "reasoning": result.reasoning,
            "warnings": result.warnings,
            "product_match_score": result.product_match_score,
        }
    )

    breakdown = calculate_profit_breakdown(
        buy_price=opportunity.buy_price,
        sell_price=opportunity.sell_price,
        marketplace_fee=opportunity.marketplace_fee,
        shipping_cost=opportunity.shipping_cost,
        tax_cost=opportunity.tax_cost,
        payment_cost=opportunity.payment_cost,
        other_cost=opportunity.other_cost,
    )
    opportunity.status = classify_opportunity(breakdown, risk_score=result.risk_score)

    db.add(opportunity)
    db.commit()
    db.refresh(opportunity)
    return opportunity
