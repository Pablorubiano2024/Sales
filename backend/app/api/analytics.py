"""Analytics summary API endpoint (Autopilot Phase 7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.security import require_api_key
from backend.app.models.lifecycle import LifecycleStage
from backend.app.schemas.analytics_summary import (
    AnalyticsSummaryResponse,
    LifecycleFunnelResponse,
    TodaySummaryResponse,
)
from backend.app.services.analytics_summary import (
    get_analytics_summary,
    get_lifecycle_funnel,
    get_today_summary,
)

router = APIRouter(
    prefix="/api/analytics", tags=["analytics"], dependencies=[Depends(require_api_key)]
)


@router.get("/summary", response_model=AnalyticsSummaryResponse)
def summary(db: Session = Depends(get_db)) -> AnalyticsSummaryResponse:
    result = get_analytics_summary(db)
    return AnalyticsSummaryResponse(
        detected_count=result.detected_count,
        published_count=result.published_count,
        sold_count=result.sold_count,
        expired_count=result.expired_count,
        avg_time_to_sale_days=result.avg_time_to_sale_days,
        avg_estimated_margin=result.avg_estimated_margin,
        avg_real_margin=result.avg_real_margin,
        confidence_recalibration={
            "sold_count": result.confidence_recalibration.sold_count,
            "expired_count": result.confidence_recalibration.expired_count,
            "avg_score_sold": result.confidence_recalibration.avg_score_sold,
            "avg_score_expired": result.confidence_recalibration.avg_score_expired,
            "directionally_correct": result.confidence_recalibration.directionally_correct,
        },
    )


@router.get("/today", response_model=TodaySummaryResponse)
def today(db: Session = Depends(get_db)) -> TodaySummaryResponse:
    result = get_today_summary(db)
    return TodaySummaryResponse(
        detected_today=result.detected_today,
        published_today=result.published_today,
        sold_today=result.sold_today,
        market_gap_events_today=result.market_gap_events_today,
    )


@router.get("/funnel", response_model=LifecycleFunnelResponse)
def funnel(db: Session = Depends(get_db)) -> LifecycleFunnelResponse:
    counts = get_lifecycle_funnel(db)
    return LifecycleFunnelResponse(
        found=counts[LifecycleStage.FOUND],
        validated=counts[LifecycleStage.VALIDATED],
        published=counts[LifecycleStage.PUBLISHED],
        sold=counts[LifecycleStage.SOLD],
        expired=counts[LifecycleStage.EXPIRED],
        cancelled=counts[LifecycleStage.CANCELLED],
    )
