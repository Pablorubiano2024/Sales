"""Analytics summary API endpoint (Autopilot Phase 7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.security import require_api_key
from backend.app.schemas.analytics_summary import AnalyticsSummaryResponse
from backend.app.services.analytics_summary import get_analytics_summary

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
