"""Pydantic schemas for Opportunity API I/O and AI analysis."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from backend.app.models.opportunity import OpportunityStatus


class OpportunityCreate(BaseModel):
    """Inputs needed to compute a new opportunity. All costs are optional
    and default to 0; the pricing engine does the math."""

    product_id: str
    source_id: str
    marketplace_id: str

    buy_price: float = Field(..., ge=0)
    sell_price: float = Field(..., ge=0)
    marketplace_fee: float = Field(0, ge=0)
    shipping_cost: float = Field(0, ge=0)
    tax_cost: float = Field(0, ge=0)
    payment_cost: float = Field(0, ge=0)
    other_cost: float = Field(0, ge=0)


class OpportunityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    product_id: str
    source_id: str
    marketplace_id: str

    buy_price: float
    sell_price: float
    marketplace_fee: float
    shipping_cost: float
    tax_cost: float
    payment_cost: float
    other_cost: float

    gross_profit: float
    net_profit: float
    roi: float
    margin: float

    competition_score: float | None = None
    demand_score: float | None = None
    risk_score: float | None = None
    ai_score: float | None = None

    status: OpportunityStatus
    ai_analysis: str | None = None

    created_at: datetime
    updated_at: datetime


class OpportunityAnalyzeRequest(BaseModel):
    """Request body for POST /api/opportunities/analyze.

    Either analyze an existing opportunity by id, or compute + classify a
    brand-new one on the fly from raw inputs.
    """

    opportunity_id: str | None = None
    inputs: OpportunityCreate | None = None
    use_ai: bool = True


class AIOpportunityAnalysis(BaseModel):
    """Structured output expected from the Claude enrichment service.

    AI analysis is enrichment only — it never overrides the deterministic
    financial calculations performed by the pricing/opportunity engines.
    """

    product_match_score: float = Field(ge=0, le=1)
    demand_score: float = Field(ge=0, le=1)
    competition_score: float = Field(ge=0, le=1)
    risk_score: float = Field(ge=0, le=1)
    overall_score: float = Field(ge=0, le=1)
    recommendation: str
    reasoning: str
    warnings: list[str] = Field(default_factory=list)
