"""Listing Draft API endpoints (Autopilot Phase 3) — the approval queue
Streamlit's autopilot view reads from and acts on."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.security import require_api_key
from backend.app.models.listing_draft import ListingDraft, ListingDraftStatus
from backend.app.models.opportunity import Opportunity
from backend.app.schemas.listing_draft import ListingDraftRead, RejectDraftRequest
from backend.app.services import category_lookup
from backend.app.services.listing_draft_service import (
    DraftGenerationError,
    approve_draft,
    fetch_live_source_data,
    generate_draft,
    reject_draft,
)

router = APIRouter(
    prefix="/api/listing-drafts", tags=["listing-drafts"], dependencies=[Depends(require_api_key)]
)


@router.get("", response_model=list[ListingDraftRead])
def list_drafts(
    status_filter: ListingDraftStatus | None = None, db: Session = Depends(get_db)
) -> list[ListingDraftRead]:
    query = db.query(ListingDraft)
    if status_filter is not None:
        query = query.filter(ListingDraft.status == status_filter)
    drafts = query.order_by(ListingDraft.created_at.desc()).all()
    return [ListingDraftRead.model_validate(d) for d in drafts]


@router.post("/generate/{opportunity_id}", response_model=ListingDraftRead)
def generate(opportunity_id: str, db: Session = Depends(get_db)) -> ListingDraftRead:
    """Fetch real live source data and build (or refresh) a ListingDraft
    for this Opportunity. Never publishes anything — see
    listing_draft_service.generate_draft's docstring. The real MercadoLibre
    commission is only computed when an account is already connected; a
    draft can still be generated/reviewed without one."""
    opportunity = db.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Opportunity not found")

    live_or_error = fetch_live_source_data(db, opportunity)
    if isinstance(live_or_error, DraftGenerationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=live_or_error.reason
        )

    with httpx.Client(
        base_url=category_lookup.API_BASE_URL, timeout=category_lookup.DEFAULT_TIMEOUT
    ) as ml_public_client:
        result = generate_draft(db, opportunity, live_or_error, ml_public_client=ml_public_client)

    if isinstance(result, DraftGenerationError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=result.reason)
    return ListingDraftRead.model_validate(result)


def _get_draft_or_404(db: Session, draft_id: str) -> ListingDraft:
    draft = db.get(ListingDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Listing draft not found")
    return draft


@router.post("/{draft_id}/approve", response_model=ListingDraftRead)
def approve(draft_id: str, db: Session = Depends(get_db)) -> ListingDraftRead:
    draft = _get_draft_or_404(db, draft_id)
    return ListingDraftRead.model_validate(approve_draft(db, draft))


@router.post("/{draft_id}/reject", response_model=ListingDraftRead)
def reject(
    draft_id: str, payload: RejectDraftRequest, db: Session = Depends(get_db)
) -> ListingDraftRead:
    draft = _get_draft_or_404(db, draft_id)
    return ListingDraftRead.model_validate(reject_draft(db, draft, payload.reason))
