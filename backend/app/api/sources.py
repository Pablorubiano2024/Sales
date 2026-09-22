"""Source API endpoints — read-only, so the frontend can show which real
source (CJdropshipping, Falabella, etc.) each opportunity came from."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.security import require_api_key
from backend.app.models.source import Source
from backend.app.schemas.source import SourceRead

router = APIRouter(prefix="/api/sources", tags=["sources"], dependencies=[Depends(require_api_key)])


@router.get("", response_model=list[SourceRead])
def list_sources(db: Session = Depends(get_db)) -> list[Source]:
    return db.query(Source).all()
