"""Gold Opportunity Alerts (Autopilot Phase 6) — sends a Slack alert only
when all three real conditions the user asked for hold at once:
  1. A real, new change just happened (a MarketGapEvent — see
     market_gap_scanner.py, the only real caller of this module).
  2. Confidence Score >= 90.
  3. Margin >= 25%.

Refreshes the Confidence Score via confidence_engine.score_opportunity()
against current real data before checking it, rather than trusting a
possibly-stale value already on the Opportunity row — reuses Phase 2's
engine, doesn't reimplement the scoring.
"""

from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.core.logging import get_logger
from backend.app.models.market_gap import MarketGapEvent, MarketGapEventType
from backend.app.models.opportunity import Opportunity
from backend.app.services.confidence_engine import score_opportunity
from backend.app.services.slack_notifier import send_slack

logger = get_logger(__name__)

MIN_ALERT_SCORE = 90
MIN_ALERT_MARGIN = Decimal("0.25")

_EVENT_LABELS: dict[MarketGapEventType, str] = {
    MarketGapEventType.LOWEST_SELLER_DISAPPEARED: "El vendedor ganador anterior desapareció",
    MarketGapEventType.BUY_BOX_PRICE_INCREASED: "El precio ganador subió",
    MarketGapEventType.SELLER_COUNT_DROPPED: "Bajó la cantidad de vendedores activos",
    MarketGapEventType.STOCK_RECOVERED: "Volvió a haber stock/vendedores activos",
}


def format_gold_opportunity_message(opportunity: Opportunity, event: MarketGapEvent) -> str:
    product_name = opportunity.product.name if opportunity.product else opportunity.product_id
    event_label = _EVENT_LABELS.get(event.event_type, event.event_type.value)

    lines = [
        f"🚨 *GOLD OPPORTUNITY* — {product_name}",
        f"Confianza: *{opportunity.confidence_score}%* · "
        f"Margen: *{opportunity.margin:.0%}* · ROI: *{opportunity.roi:.0%}*",
        "",
        f"*Cambio detectado:* {event_label}",
    ]
    if event.detail:
        lines.append(f"    {event.detail}")

    if opportunity.confidence_breakdown:
        try:
            breakdown = json.loads(opportunity.confidence_breakdown)
            lines.append("")
            lines.append("*Por qué:*")
            for factor in breakdown:
                lines.append(f"- {factor['label']} (+{factor['points']}): {factor['reasoning']}")
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

    return "\n".join(lines)


def maybe_alert_gold_opportunity(
    db: Session, opportunity: Opportunity, event: MarketGapEvent
) -> bool:
    """Returns whether an alert was actually sent."""
    opportunity = score_opportunity(db, opportunity)

    if opportunity.confidence_score is None or opportunity.confidence_score < MIN_ALERT_SCORE:
        return False
    if opportunity.margin < MIN_ALERT_MARGIN:
        return False

    return send_slack(format_gold_opportunity_message(opportunity, event))
