"""Market Gap Events API (Autopilot Phase 7) — real, detected Buy Box
changes (see backend/app/jobs/market_gap_scanner.py), surfaced for the
Streamlit Autopilot dashboard. Previously only visible via Slack alerts
(and only for ones that cleared the Gold Opportunity thresholds) or by
querying the database directly."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.security import require_api_key
from backend.app.models.market_gap import MarketGapEvent
from backend.app.models.opportunity import Opportunity
from backend.app.models.product import Product
from backend.app.schemas.market_gap_event import MarketGapEventRead

router = APIRouter(
    prefix="/api/market-gap-events",
    tags=["market-gap-events"],
    dependencies=[Depends(require_api_key)],
)


@router.get("", response_model=list[MarketGapEventRead])
def list_market_gap_events(
    limit: int = 50, db: Session = Depends(get_db)
) -> list[MarketGapEventRead]:
    rows = (
        db.query(MarketGapEvent, Product.name)
        .outerjoin(Opportunity, Opportunity.id == MarketGapEvent.opportunity_id)
        .outerjoin(Product, Product.id == Opportunity.product_id)
        .order_by(MarketGapEvent.detected_at.desc())
        .limit(limit)
        .all()
    )
    return [
        MarketGapEventRead(
            id=event.id,
            catalog_product_id=event.catalog_product_id,
            opportunity_id=event.opportunity_id,
            product_name=product_name,
            event_type=event.event_type,
            detail=event.detail,
            detected_at=event.detected_at,
        )
        for event, product_name in rows
    ]
