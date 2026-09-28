"""Analytics summary (Autopilot Phase 7) — aggregates the real
AnalyticsEvent rows written by arbitrage_engine.py (DETECTED),
scripts/publish_approved_opportunities.py (PUBLISHED), and
order_router.py (SOLD) into the numbers the user asked for: how many
opportunities were detected/published/sold, real time-to-sale, and
estimated vs. real margin — the same real data source
confidence_engine.recalibrate_weights() already reads to check whether
the Confidence Score tracks real outcomes, reused here rather than
reimplemented.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.app.models.analytics import AnalyticsEvent, AnalyticsEventType
from backend.app.services.confidence_engine import RecalibrationReport, recalibrate_weights


@dataclass(frozen=True, slots=True)
class AnalyticsSummary:
    detected_count: int
    published_count: int
    sold_count: int
    expired_count: int
    avg_time_to_sale_days: float | None
    avg_estimated_margin: float | None
    avg_real_margin: float | None
    confidence_recalibration: RecalibrationReport


def _count(db: Session, event_type: AnalyticsEventType) -> int:
    return db.query(AnalyticsEvent).filter_by(event_type=event_type).count()


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def get_analytics_summary(db: Session) -> AnalyticsSummary:
    sold_rows = db.query(AnalyticsEvent).filter_by(event_type=AnalyticsEventType.SOLD).all()

    time_to_sale_minutes = [
        r.time_to_sale_minutes for r in sold_rows if r.time_to_sale_minutes is not None
    ]
    estimated_margins = [
        float(r.estimated_margin) for r in sold_rows if r.estimated_margin is not None
    ]
    real_margins = [float(r.real_margin) for r in sold_rows if r.real_margin is not None]

    avg_time_to_sale_minutes = _avg([float(m) for m in time_to_sale_minutes])

    return AnalyticsSummary(
        detected_count=_count(db, AnalyticsEventType.DETECTED),
        published_count=_count(db, AnalyticsEventType.PUBLISHED),
        sold_count=_count(db, AnalyticsEventType.SOLD),
        expired_count=_count(db, AnalyticsEventType.EXPIRED),
        avg_time_to_sale_days=(
            avg_time_to_sale_minutes / 1440 if avg_time_to_sale_minutes is not None else None
        ),
        avg_estimated_margin=_avg(estimated_margins),
        avg_real_margin=_avg(real_margins),
        confidence_recalibration=recalibrate_weights(db),
    )
