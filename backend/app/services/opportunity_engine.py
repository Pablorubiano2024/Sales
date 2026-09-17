"""Opportunity classification engine.

Classifies a computed ProfitBreakdown into an OpportunityStatus using
configurable thresholds (from Settings, never hard-coded). This is a
purely mathematical/deterministic qualification step — no AI involved.
"""

from __future__ import annotations

from decimal import Decimal

from backend.app.core.config import Settings, get_settings
from backend.app.models.opportunity import OpportunityStatus
from backend.app.services.pricing_engine import ProfitBreakdown


def classify_opportunity(
    breakdown: ProfitBreakdown,
    risk_score: float | None = None,
    settings: Settings | None = None,
) -> OpportunityStatus:
    """Classify an opportunity based on ROI, net profit and (optional) risk.

    Rules (defaults, configurable via Settings):
      - net_profit <= 0                          -> REJECTED
      - roi < min_roi OR net_profit < min_net     -> REJECTED
      - risk_score > max_risk_score (if known)    -> REVIEW
      - roi >= min_roi and net_profit >= min_net  -> PROMISING
      - PROMISING with comfortable margin (>=2x
        thresholds) and acceptable risk           -> APPROVED
    """
    settings = settings or get_settings()

    min_roi = settings.min_roi
    min_net_profit = settings.min_net_profit
    max_risk_score = settings.max_risk_score

    if breakdown.net_profit <= 0:
        return OpportunityStatus.REJECTED

    if breakdown.roi < min_roi or breakdown.net_profit < min_net_profit:
        return OpportunityStatus.REJECTED

    if risk_score is not None and risk_score > max_risk_score:
        return OpportunityStatus.REVIEW

    comfortably_above = breakdown.roi >= min_roi * Decimal(
        "2"
    ) and breakdown.net_profit >= min_net_profit * Decimal("2")
    if comfortably_above and (risk_score is None or risk_score <= max_risk_score / 2):
        return OpportunityStatus.APPROVED

    return OpportunityStatus.PROMISING
