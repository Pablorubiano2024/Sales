"""Opportunity API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.opportunity import Opportunity, OpportunityStatus
from backend.app.schemas.opportunity import OpportunityAnalyzeRequest, OpportunityRead
from backend.app.services.ai_service import enrich_opportunity_with_ai
from backend.app.services.arbitrage_engine import evaluate_opportunity

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])


@router.get("", response_model=list[OpportunityRead])
def list_opportunities(
    status_filter: OpportunityStatus | None = None,
    min_roi: float | None = None,
    min_net_profit: float | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[Opportunity]:
    query = db.query(Opportunity)
    if status_filter is not None:
        query = query.filter(Opportunity.status == status_filter)
    if min_roi is not None:
        query = query.filter(Opportunity.roi >= min_roi)
    if min_net_profit is not None:
        query = query.filter(Opportunity.net_profit >= min_net_profit)
    return query.order_by(Opportunity.net_profit.desc()).offset(offset).limit(limit).all()


@router.get("/{opportunity_id}", response_model=OpportunityRead)
def get_opportunity(opportunity_id: str, db: Session = Depends(get_db)) -> Opportunity:
    opportunity = db.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")
    return opportunity


@router.post("/analyze", response_model=OpportunityRead)
def analyze_opportunity(
    payload: OpportunityAnalyzeRequest, db: Session = Depends(get_db)
) -> Opportunity:
    """Compute (or re-analyze) an opportunity. Financial math always runs
    deterministically; AI enrichment (`use_ai=True`, the default) is
    best-effort on top and never blocks the response."""
    if payload.opportunity_id is not None:
        opportunity = db.get(Opportunity, payload.opportunity_id)
        if opportunity is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found"
            )
    elif payload.inputs is not None:
        opportunity = evaluate_opportunity(db, payload.inputs)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either opportunity_id or inputs must be provided",
        )

    if payload.use_ai:
        opportunity = enrich_opportunity_with_ai(db, opportunity)

    return opportunity
