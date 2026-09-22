"""MercadoLibre marketplace adapter.

OAuth2 (Authorization Code, server-side) is REAL and wired up — see
`backend/app/api/mercadolibre_oauth.py` for the `/authorize` + `/callback`
endpoints that get an access_token/refresh_token onto a
`MarketplaceCredential` row, and that module's docstring for the verified
source (MercadoLibre's own docs, checked live 2026-09-21).

Every OTHER method below (search_products, create_listing, get_orders,
etc.) is still a skeleton — this codebase must never pretend an endpoint
works when it hasn't been verified against MercadoLibre's real API (see
PROJECT_CONTEXT.md, principle #4: "Never invent API endpoints"). Each
raises NotImplementedError with a TODO naming the endpoint to confirm
before implementing it, the same pattern used while building the
CJdropshipping adapter (verify one endpoint at a time against real
responses, never guess a payload shape).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.core.time import utcnow
from backend.app.integrations.base import (
    MarketplaceAdapter,
    MarketplaceListingInfo,
    MarketplaceOrderInfo,
)
from backend.app.models.marketplace import Marketplace
from backend.app.models.marketplace_credential import MarketplaceCredential

logger = get_logger(__name__)

API_BASE_URL = "https://api.mercadolibre.com"
TOKEN_URL = f"{API_BASE_URL}/oauth/token"
DEFAULT_TIMEOUT = 15.0
MARKETPLACE_NAME = "MercadoLibre Colombia"
# Refresh a little before the real 6h expiry to avoid a request racing the
# exact expiry instant.
EXPIRY_SAFETY_MARGIN = timedelta(minutes=5)


class MercadoLibreAdapter(MarketplaceAdapter):
    """Adapter for MercadoLibre Colombia. Requires a `db.Session` because,
    unlike a stateless API-key source like CJdropshipping, it has to load
    (and persist refreshed) OAuth tokens tied to our `MarketplaceCredential`
    row."""

    def __init__(
        self,
        db: Session,
        base_url: str = API_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = get_settings()
        self._db = db
        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)
        self._authenticated = False
        self._access_token: str | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> MercadoLibreAdapter:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _get_credential(self) -> MarketplaceCredential | None:
        marketplace = self._db.query(Marketplace).filter_by(name=MARKETPLACE_NAME).first()
        if marketplace is None:
            return None
        return (
            self._db.query(MarketplaceCredential).filter_by(marketplace_id=marketplace.id).first()
        )

    def _refresh(self, credential: MarketplaceCredential) -> bool:
        if not self._settings.ml_client_id or not self._settings.ml_client_secret:
            logger.warning("Cannot refresh MercadoLibre token: ML_CLIENT_ID/SECRET not set.")
            return False

        response = self._client.post(
            "/oauth/token",
            headers={
                "accept": "application/json",
                "content-type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "refresh_token",
                "client_id": self._settings.ml_client_id,
                "client_secret": self._settings.ml_client_secret,
                "refresh_token": credential.refresh_token,
            },
        )
        if response.status_code != 200:
            logger.warning("MercadoLibre token refresh failed: %s", response.text)
            return False

        payload = response.json()
        credential.access_token = payload["access_token"]
        # The refresh_token is single-use — MercadoLibre always returns a
        # new one that MUST replace the old one, or the next refresh fails.
        credential.refresh_token = payload["refresh_token"]
        credential.expires_at = utcnow() + timedelta(seconds=payload["expires_in"])
        self._db.commit()
        return True

    def authenticate(self) -> bool:
        credential = self._get_credential()
        if credential is None:
            logger.warning(
                "No MercadoLibre credential stored yet — connect the account first via "
                "GET /api/marketplaces/mercadolibre/authorize."
            )
            self._authenticated = False
            return False

        if credential.expires_at <= utcnow() + EXPIRY_SAFETY_MARGIN and not self._refresh(
            credential
        ):
            self._authenticated = False
            return False

        # Verify the token actually works against a real endpoint rather
        # than trusting a stored expiry — the same "confirm it live" habit
        # used for CJdropshipping's auth.
        response = self._client.get(
            "/users/me", headers={"Authorization": f"Bearer {credential.access_token}"}
        )
        if response.status_code != 200:
            logger.warning("MercadoLibre /users/me check failed: %s", response.text)
            self._authenticated = False
            return False

        self._access_token = credential.access_token
        self._authenticated = True
        logger.info("MercadoLibre authenticated as user_id=%s", response.json().get("id"))
        return True

    def search_products(self, query: str, limit: int = 20) -> list[MarketplaceListingInfo]:
        # TODO: GET /sites/{site_id}/search?q=... — confirm exact response
        # shape against a real call before implementing.
        raise NotImplementedError(
            "MercadoLibre search_products: endpoint not yet verified against real responses."
        )

    def get_product(self, external_id: str) -> MarketplaceListingInfo | None:
        # TODO: GET /items/{item_id}
        raise NotImplementedError(
            "MercadoLibre get_product: endpoint not yet verified against real responses."
        )

    def get_listing(self, external_id: str) -> MarketplaceListingInfo | None:
        # TODO: GET /items/{item_id} (our own listing)
        raise NotImplementedError(
            "MercadoLibre get_listing: endpoint not yet verified against real responses."
        )

    def create_listing(
        self,
        product_id: str,
        title: str,
        price: Decimal,
        currency: str,
        *,
        category_id: str | None = None,
        brand: str = "Generic",
        model: str = "Genérico",
        condition: str = "new",
        listing_type_id: str = "free",
        available_quantity: int = 1,
        pictures: list[str] | None = None,
    ) -> MarketplaceListingInfo:
        """POST /items. Payload verified against MercadoLibre's own docs
        (developers.mercadolibre.com.ar/publica-productos, updated
        2026-01-09) and a real category's required attributes (checked live
        2026-09-21: GET /categories/{id}/attributes). `category_id` has no
        sane default — every category has different required attributes, so
        this deliberately isn't looked up automatically yet (that needs a
        real category-prediction step per product, not built here). `brand`
        MUST be a value this category actually accepts (many, not all,
        accept "Generic" for unbranded products) — check
        GET /categories/{category_id}/attributes first.

        MercadoLibre has no sandbox (see "Realiza pruebas" docs) — this
        creates a REAL, public, live listing on the connected seller
        account. `listing_type_id="free"` avoids any cost."""
        if not self._authenticated or self._access_token is None:
            raise RuntimeError("Call authenticate() before create_listing().")
        if category_id is None:
            raise ValueError(
                "category_id is required — every MercadoLibre category has different "
                "required attributes, so there's no sane default. Look one up first via "
                "GET /sites/{site_id}/domain_discovery/search?q=<title>."
            )

        payload: dict[str, Any] = {
            "title": title,
            "category_id": category_id,
            "price": float(price),
            "currency_id": currency,
            "available_quantity": available_quantity,
            "buying_mode": "buy_it_now",
            "condition": condition,
            "listing_type_id": listing_type_id,
            "attributes": [
                {"id": "BRAND", "value_name": brand},
                {"id": "MODEL", "value_name": model},
            ],
        }
        if pictures:
            payload["pictures"] = [{"source": url} for url in pictures]

        response = self._client.post(
            "/items",
            headers={"Authorization": f"Bearer {self._access_token}"},
            json=payload,
        )
        if response.status_code not in (200, 201):
            logger.error("MercadoLibre create_listing failed: %s", response.text)
            raise RuntimeError(
                f"MercadoLibre create_listing failed ({response.status_code}): {response.text}"
            )

        data = response.json()
        return MarketplaceListingInfo(
            external_id=data["id"],
            title=data["title"],
            price=Decimal(str(data["price"])),
            currency=data["currency_id"],
            status=data["status"],
            url=data.get("permalink"),
            raw=data,
        )

    def update_listing(self, external_id: str, **fields: Any) -> MarketplaceListingInfo:
        # TODO: PUT /items/{item_id}
        raise NotImplementedError(
            "MercadoLibre update_listing: endpoint not yet verified against real responses."
        )

    def update_price(self, external_id: str, price: Decimal) -> None:
        # TODO: PUT /items/{item_id} with {"price": ...}
        raise NotImplementedError(
            "MercadoLibre update_price: endpoint not yet verified against real responses."
        )

    def update_stock(self, external_id: str, in_stock: bool) -> None:
        # TODO: PUT /items/{item_id} with {"available_quantity": ...}
        raise NotImplementedError(
            "MercadoLibre update_stock: endpoint not yet verified against real responses."
        )

    def get_orders(self, since: str | None = None) -> list[MarketplaceOrderInfo]:
        # TODO: GET /orders/search?seller={user_id} — this is the piece
        # Phase 6 (order monitoring) needs; the OAuth "Venta y envíos de un
        # producto" scope was granted for exactly this.
        raise NotImplementedError(
            "MercadoLibre get_orders: endpoint not yet verified against real responses."
        )
