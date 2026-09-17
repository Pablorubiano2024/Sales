"""Marketplace API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.models.marketplace import Marketplace
from backend.app.schemas.marketplace import MarketplaceRead

router = APIRouter(prefix="/api/marketplaces", tags=["marketplaces"])


@router.get("", response_model=list[MarketplaceRead])
def list_marketplaces(db: Session = Depends(get_db)) -> list[Marketplace]:
    return db.query(Marketplace).all()
