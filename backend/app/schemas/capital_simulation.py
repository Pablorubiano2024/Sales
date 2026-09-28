"""Pydantic schemas for the Capital Simulator API (Autopilot Phase 7)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CapitalSimulationRequest(BaseModel):
    capital: float = Field(..., gt=0)
    max_daily_purchases: int = Field(..., gt=0)
    min_margin: float = Field(..., ge=0)


class CapitalSimulationResponse(BaseModel):
    qualifying_opportunities: int
    avg_buy_price: float
    avg_margin: float
    avg_net_profit_per_sale: float
    avg_time_to_sale_days: float
    time_to_sale_is_real_data: bool

    daily_purchases: float
    daily_capital_deployed: float
    daily_profit: float
    monthly_profit: float
    monthly_roi: float
    capital_rotations_per_month: float
    days_to_double_capital: float | None
