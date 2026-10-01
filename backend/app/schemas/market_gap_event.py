"""Pydantic schemas for the Market Gap Events API (Autopilot Phase 7)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from backend.app.models.market_gap import MarketGapEventType


class MarketGapEventRead(BaseModel):
    id: str
    catalog_product_id: str
    opportunity_id: str | None = None
    product_name: str | None = None
    event_type: MarketGapEventType
    detail: str | None = None
    detected_at: datetime
