"""Pydantic schemas for the Analytics Summary API (Autopilot Phase 7)."""

from __future__ import annotations

from pydantic import BaseModel


class ConfidenceRecalibrationRead(BaseModel):
    sold_count: int
    expired_count: int
    avg_score_sold: float | None
    avg_score_expired: float | None
    directionally_correct: bool | None


class AnalyticsSummaryResponse(BaseModel):
    detected_count: int
    published_count: int
    sold_count: int
    expired_count: int
    avg_time_to_sale_days: float | None
    avg_estimated_margin: float | None
    avg_real_margin: float | None
    confidence_recalibration: ConfidenceRecalibrationRead
