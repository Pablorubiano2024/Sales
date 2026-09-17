"""MercadoLibre marketplace adapter — SKELETON ONLY.

IMPORTANT: This adapter does NOT call the real MercadoLibre API. We do not
yet have verified endpoint documentation or OAuth credentials wired in, and
this codebase must never pretend an integration works when it hasn't been
verified (see PROJECT_CONTEXT.md, principle #4: "Never invent API
endpoints").

To make this real:
  1. Register a MercadoLibre application at https://developers.mercadolibre.com
  2. Implement the OAuth2 authorization-code flow (client_id/secret,
     redirect_uri, refresh tokens) in `authenticate()`.
  3. Wire the confirmed REST endpoints (items, orders, questions, etc.)
     from MercadoLibre's official docs into each method below.
  4. Add `ml_client_id` / `ml_client_secret` / `ml_refresh_token` to
     `backend.app.core.config.Settings` and `.env.example`.

Every public method currently raises NotImplementedError with a TODO
pointing at what's missing, so callers fail loudly instead of silently
getting fake data. `authenticate()` returns False when no credentials are
configured, which is what callers should check before attempting anything
else.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.integrations.base import (
    MarketplaceAdapter,
    MarketplaceListingInfo,
    MarketplaceOrderInfo,
)

logger = get_logger(__name__)


class MercadoLibreAdapter(MarketplaceAdapter):
    """Skeleton adapter for MercadoLibre. Not functional yet — see module docstring."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._authenticated = False

    def authenticate(self) -> bool:
        # TODO: implement OAuth2 authorization-code flow once ML app
        # credentials exist. No credentials configured -> not authenticated.
        logger.warning(
            "MercadoLibreAdapter.authenticate() called but no credentials are "
            "configured yet; MercadoLibre integration is not implemented."
        )
        self._authenticated = False
        return self._authenticated

    def search_products(self, query: str, limit: int = 20) -> list[MarketplaceListingInfo]:
        # TODO: GET https://api.mercadolibre.com/sites/{site_id}/search?q=...
        # (endpoint to be confirmed against official docs before use).
        raise NotImplementedError(
            "MercadoLibre search_products requires verified API credentials/docs."
        )

    def get_product(self, external_id: str) -> MarketplaceListingInfo | None:
        # TODO: GET https://api.mercadolibre.com/items/{item_id} (confirm before use).
        raise NotImplementedError(
            "MercadoLibre get_product requires verified API credentials/docs."
        )

    def get_listing(self, external_id: str) -> MarketplaceListingInfo | None:
        # TODO: fetch our own item listing details.
        raise NotImplementedError(
            "MercadoLibre get_listing requires verified API credentials/docs."
        )

    def create_listing(
        self, product_id: str, title: str, price: Decimal, currency: str
    ) -> MarketplaceListingInfo:
        # TODO: POST /items — requires OAuth token and confirmed payload schema.
        raise NotImplementedError(
            "MercadoLibre create_listing requires verified API credentials/docs."
        )

    def update_listing(self, external_id: str, **fields: Any) -> MarketplaceListingInfo:
        # TODO: PUT /items/{item_id}
        raise NotImplementedError(
            "MercadoLibre update_listing requires verified API credentials/docs."
        )

    def update_price(self, external_id: str, price: Decimal) -> None:
        # TODO: PUT /items/{item_id} with price field.
        raise NotImplementedError(
            "MercadoLibre update_price requires verified API credentials/docs."
        )

    def update_stock(self, external_id: str, in_stock: bool) -> None:
        # TODO: PUT /items/{item_id} with available_quantity field.
        raise NotImplementedError(
            "MercadoLibre update_stock requires verified API credentials/docs."
        )

    def get_orders(self, since: str | None = None) -> list[MarketplaceOrderInfo]:
        # TODO: GET /orders/search?seller={user_id}
        raise NotImplementedError("MercadoLibre get_orders requires verified API credentials/docs.")
