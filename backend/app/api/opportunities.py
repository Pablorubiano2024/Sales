"""Opportunity API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.security import require_api_key
from backend.app.models.opportunity import Opportunity, OpportunityStatus
from backend.app.models.source import SourceProduct
from backend.app.schemas.opportunity import OpportunityAnalyzeRequest, OpportunityRead
from backend.app.schemas.validation import ValidationResultRead
from backend.app.services.ai_service import enrich_opportunity_with_ai
from backend.app.services.arbitrage_engine import evaluate_opportunity
from backend.app.services.confidence_engine import score_opportunity
from backend.app.services.listing_draft_service import DraftGenerationError, fetch_live_source_data
from backend.app.services.opportunity_validator import validate_opportunity

router = APIRouter(
    prefix="/api/opportunities", tags=["opportunities"], dependencies=[Depends(require_api_key)]
)


def _with_source_url(db: Session, opportunities: list[Opportunity]) -> list[OpportunityRead]:
    """Attach each opportunity's real source purchase URL (from its
    matching SourceProduct row) — so a buyer can go straight to where to
    buy the item as soon as a MercadoLibre sale happens. One batched query
    instead of N+1."""
    pairs = {(o.source_id, o.product_id) for o in opportunities}
    if not pairs:
        return []
    source_products = (
        db.query(SourceProduct)
        .filter(
            SourceProduct.source_id.in_({p[0] for p in pairs}),
            SourceProduct.product_id.in_({p[1] for p in pairs}),
        )
        .all()
    )
    url_by_pair = {(sp.source_id, sp.product_id): sp.url for sp in source_products}
    return [
        OpportunityRead.model_validate(o).model_copy(
            update={"source_url": url_by_pair.get((o.source_id, o.product_id))}
        )
        for o in opportunities
    ]


@router.get("", response_model=list[OpportunityRead])
def list_opportunities(
    status_filter: OpportunityStatus | None = None,
    min_roi: float | None = None,
    min_net_profit: float | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[OpportunityRead]:
    query = db.query(Opportunity)
    if status_filter is not None:
        query = query.filter(Opportunity.status == status_filter)
    if min_roi is not None:
        query = query.filter(Opportunity.roi >= min_roi)
    if min_net_profit is not None:
        query = query.filter(Opportunity.net_profit >= min_net_profit)
    opportunities = query.order_by(Opportunity.net_profit.desc()).offset(offset).limit(limit).all()
    return _with_source_url(db, opportunities)


@router.get("/{opportunity_id}", response_model=OpportunityRead)
def get_opportunity(opportunity_id: str, db: Session = Depends(get_db)) -> OpportunityRead:
    opportunity = db.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")
    return _with_source_url(db, [opportunity])[0]


@router.post("/analyze", response_model=OpportunityRead)
def analyze_opportunity(
    payload: OpportunityAnalyzeRequest, db: Session = Depends(get_db)
) -> OpportunityRead:
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

    # Deterministic — always runs, independent of use_ai, so the
    # Autopilot Confidence Score/breakdown is always fresh on this
    # response (see confidence_engine.py for the explainable breakdown).
    opportunity = score_opportunity(db, opportunity)

    return _with_source_url(db, [opportunity])[0]


@router.get("/{opportunity_id}/validate", response_model=ValidationResultRead)
def validate(
    opportunity_id: str, refresh_live: bool = False, db: Session = Depends(get_db)
) -> ValidationResultRead:
    """Run the Opportunity Validator (Autopilot Phase 1) rules for one
    opportunity. `refresh_live=True` re-fetches real stock/price from the
    source first (same fetch publish_approved_opportunities.py does) —
    otherwise stock/price checks report "not applicable" since nothing
    live was checked."""
    opportunity = db.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")

    live_stock_available = None
    live_price_cop = None
    if refresh_live:
        live_or_error = fetch_live_source_data(db, opportunity)
        if isinstance(live_or_error, DraftGenerationError):
            live_stock_available = False
        else:
            live_stock_available = live_or_error.stock_available
            live_price_cop = live_or_error.price

    result = validate_opportunity(
        db,
        opportunity,
        live_stock_available=live_stock_available,
        live_price_cop=live_price_cop,
    )
    return ValidationResultRead(
        checks=[{"name": c.name, "passed": c.passed, "detail": c.detail} for c in result.checks],
        overall_passed=result.overall_passed,
    )
