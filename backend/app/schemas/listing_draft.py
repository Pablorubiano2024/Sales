"""Pydantic schemas for the Autopilot Listing Draft API (Phase 3)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from backend.app.models.listing_draft import ListingDraftStatus


class ListingDraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    opportunity_id: str
    title: str
    description: str | None = None
    bullets: str | None = None  # JSON-encoded list[str]
    attributes: str | None = None  # JSON-encoded dict
    image_urls: str | None = None  # JSON-encoded list[str]
    category_id: str | None = None
    price: float
    status: ListingDraftStatus
    rejection_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class RejectDraftRequest(BaseModel):
    reason: str
