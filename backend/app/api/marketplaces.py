"""Marketplace API endpoints.

The OAuth flow itself (`/mercadolibre/authorize`, `/mercadolibre/callback`)
lives in `mercadolibre_oauth.py` on its own unauthenticated router — those
are hit by browser redirects that can't carry our `X-API-Key`. This router
covers everything else, which the frontend calls normally (with the key).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.security import require_api_key
from backend.app.models.marketplace import Marketplace
from backend.app.models.marketplace_credential import MarketplaceCredential
from backend.app.schemas.marketplace import MarketplaceRead

router = APIRouter(
    prefix="/api/marketplaces", tags=["marketplaces"], dependencies=[Depends(require_api_key)]
)


@router.get("", response_model=list[MarketplaceRead])
def list_marketplaces(db: Session = Depends(get_db)) -> list[Marketplace]:
    return db.query(Marketplace).all()


class MercadoLibreStatus(BaseModel):
    connected: bool
    external_user_id: str | None = None
    scope: str | None = None
    expires_at: str | None = None


@router.get("/mercadolibre/status", response_model=MercadoLibreStatus)
def mercadolibre_status(db: Session = Depends(get_db)) -> MercadoLibreStatus:
    marketplace = db.query(Marketplace).filter_by(name="MercadoLibre Colombia").first()
    credential = (
        db.query(MarketplaceCredential).filter_by(marketplace_id=marketplace.id).first()
        if marketplace is not None
        else None
    )
    if credential is None:
        return MercadoLibreStatus(connected=False)
    return MercadoLibreStatus(
        # "Connected" here means we hold a token, not that it's still valid
        # this instant — MercadoLibreAdapter.authenticate() is what
        # actually refreshes/verifies it live before use.
        connected=True,
        external_user_id=credential.external_user_id,
        scope=credential.scope,
        expires_at=credential.expires_at.isoformat(),
    )
