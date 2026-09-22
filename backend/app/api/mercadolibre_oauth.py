"""MercadoLibre OAuth2 flow (Authorization Code, server-side).

Deliberately a SEPARATE router from `marketplaces.router` — it must NOT
require `X-API-Key` (`require_api_key`). These two endpoints are hit by the
seller's own browser via redirects from auth.mercadolibre.com.co /
api.mercadolibre.com, which cannot attach our internal API key header. The
`code` MercadoLibre hands back is single-use and only redeemable with our
registered `redirect_uri` + client_secret, so leaving these unauthenticated
is how every OAuth callback works, not a gap.

Flow, verified against MercadoLibre's own docs
(developers.mercadolibre.com.ar/es_ar/autenticacion-y-autorizacion,
last updated 2026-07-15, and .../crea-una-aplicacion-en-mercado-libre-es,
2026-08-06) on 2026-09-21:

  1. GET /authorize -> 307 redirect to
     https://auth.mercadolibre.com.co/authorization?response_type=code&
     client_id=...&redirect_uri=...
  2. Seller logs in / grants access on MercadoLibre's own page.
  3. MercadoLibre redirects the browser to our registered redirect_uri with
     ?code=..., which lands on GET /callback here.
  4. /callback exchanges the code for an access_token + refresh_token via
     POST https://api.mercadolibre.com/oauth/token (grant_type=
     authorization_code), and stores both against the "MercadoLibre
     Colombia" Marketplace row.

access_token expires in 6 hours; refresh_token is single-use (each refresh
returns a new one) and expires after 6 months of not being used — see
`MercadoLibreAdapter.authenticate()` for the refresh side.
"""

from __future__ import annotations

from datetime import timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.database import get_db
from backend.app.core.logging import get_logger
from backend.app.core.time import utcnow
from backend.app.models.marketplace import Marketplace
from backend.app.models.marketplace_credential import MarketplaceCredential

logger = get_logger(__name__)

router = APIRouter(prefix="/api/marketplaces/mercadolibre", tags=["mercadolibre-oauth"])

AUTH_URL = "https://auth.mercadolibre.com.co/authorization"
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
MARKETPLACE_NAME = "MercadoLibre Colombia"


def _get_or_create_marketplace(db: Session) -> Marketplace:
    marketplace = db.query(Marketplace).filter_by(name=MARKETPLACE_NAME).first()
    if marketplace is None:
        marketplace = Marketplace(name=MARKETPLACE_NAME, country="CO")
        db.add(marketplace)
        db.commit()
        db.refresh(marketplace)
    return marketplace


@router.get("/authorize")
def authorize() -> RedirectResponse:
    settings = get_settings()
    if not settings.ml_client_id or not settings.ml_redirect_uri:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ML_CLIENT_ID / ML_REDIRECT_URI not configured — set them before connecting.",
        )
    url = (
        f"{AUTH_URL}?response_type=code"
        f"&client_id={settings.ml_client_id}"
        f"&redirect_uri={settings.ml_redirect_uri}"
    )
    return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/callback", response_class=HTMLResponse)
def callback(code: str = Query(...), db: Session = Depends(get_db)) -> str:
    settings = get_settings()
    if not settings.ml_client_id or not settings.ml_client_secret or not settings.ml_redirect_uri:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MercadoLibre OAuth settings are not fully configured.",
        )

    with httpx.Client(timeout=15.0) as client:
        response = client.post(
            TOKEN_URL,
            headers={
                "accept": "application/json",
                "content-type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "client_id": settings.ml_client_id,
                "client_secret": settings.ml_client_secret,
                "code": code,
                "redirect_uri": settings.ml_redirect_uri,
            },
        )

    if response.status_code != 200:
        logger.error("MercadoLibre token exchange failed: %s", response.text)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"MercadoLibre token exchange failed: {response.text}",
        )

    payload = response.json()
    marketplace = _get_or_create_marketplace(db)

    credential = db.query(MarketplaceCredential).filter_by(marketplace_id=marketplace.id).first()
    if credential is None:
        credential = MarketplaceCredential(marketplace_id=marketplace.id)
        db.add(credential)

    credential.access_token = payload["access_token"]
    credential.refresh_token = payload["refresh_token"]
    credential.token_type = payload.get("token_type", "bearer")
    credential.scope = payload.get("scope")
    credential.external_user_id = str(payload.get("user_id", ""))
    credential.expires_at = utcnow() + timedelta(seconds=payload["expires_in"])
    db.commit()

    logger.info(
        "MercadoLibre account connected: user_id=%s scope=%s",
        credential.external_user_id,
        credential.scope,
    )
    return (
        "<html><body style='font-family:sans-serif;padding:40px;text-align:center'>"
        "<h2>Cuenta de MercadoLibre conectada correctamente</h2>"
        "<p>Ya puedes cerrar esta pestaña y volver al panel.</p>"
        "</body></html>"
    )
