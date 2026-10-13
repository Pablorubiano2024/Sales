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
        self._user_id: int | None = None

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
        self._user_id = response.json().get("id")
        logger.info("MercadoLibre authenticated as user_id=%s", self._user_id)
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
        """GET /items/{item_id}. Verified live 2026-09-22: a freshly
        created item's status in the create_listing response can be a
        transient value (e.g. "paused" pending an async review) that
        resolves to "active"/"under_review"/etc. moments later — callers
        that need the current real state (the daily sync job) must
        re-fetch via this method rather than trust the creation-time
        status forever."""
        if not self._authenticated or self._access_token is None:
            raise RuntimeError("Call authenticate() before get_listing().")

        response = self._client.get(
            f"/items/{external_id}", headers={"Authorization": f"Bearer {self._access_token}"}
        )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            logger.error("MercadoLibre get_listing failed: %s", response.text)
            raise RuntimeError(
                f"MercadoLibre get_listing failed ({response.status_code}): {response.text}"
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
        extra_attributes: list[dict[str, str]] | None = None,
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

        # COP (and other zero-decimal currencies) reject a price with any
        # decimal precision at all — confirmed live 2026-09-21
        # ("item.price.invalid: Currency Peso colombiano (COP) does not
        # support decimal precision") — so a whole-number Decimal must be
        # sent as an int, not 5000.0.
        price_value: float | int = (
            int(price) if price == price.to_integral_value() else float(price)
        )

        payload: dict[str, Any] = {
            "title": title,
            "category_id": category_id,
            "price": price_value,
            "currency_id": currency,
            "available_quantity": available_quantity,
            "buying_mode": "buy_it_now",
            "condition": condition,
            "listing_type_id": listing_type_id,
            "attributes": [
                {"id": "BRAND", "value_name": brand},
                {"id": "MODEL", "value_name": model},
                *(extra_attributes or []),
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
        """PUT /items/{item_id}. Verified live 2026-09-21 with {"status":
        "paused"} — same endpoint accepts any updatable item field
        (price, available_quantity, title while unsold, etc.), one call."""
        if not self._authenticated or self._access_token is None:
            raise RuntimeError("Call authenticate() before update_listing().")

        response = self._client.put(
            f"/items/{external_id}",
            headers={"Authorization": f"Bearer {self._access_token}"},
            json=fields,
        )
        if response.status_code != 200:
            logger.error("MercadoLibre update_listing failed: %s", response.text)
            raise RuntimeError(
                f"MercadoLibre update_listing failed ({response.status_code}): {response.text}"
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

    def update_price(self, external_id: str, price: Decimal) -> None:
        # Same COP-decimal-precision constraint as create_listing (see its
        # docstring) — a whole-number Decimal must be sent as an int.
        price_value: float | int = (
            int(price) if price == price.to_integral_value() else float(price)
        )
        self.update_listing(external_id, price=price_value)

    def _auth_headers(self) -> dict[str, str]:
        if not self._authenticated or self._access_token is None:
            raise RuntimeError("Call authenticate() first.")
        return {"Authorization": f"Bearer {self._access_token}"}

    def change_listing_type(self, external_id: str, listing_type_id: str) -> None:
        """POST /items/{item_id}/listing_type. Verified live 2026-10-09
        upgrading 5 real "free" items to "gold_special" (HTTP 200)."""
        response = self._client.post(
            f"/items/{external_id}/listing_type",
            headers=self._auth_headers(),
            json={"id": listing_type_id},
        )
        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"MercadoLibre change_listing_type failed ({response.status_code}): {response.text}"
            )

    def set_free_shipping(self, external_id: str) -> None:
        """PUT /items/{item_id} {"shipping": {"free_shipping": true}} —
        verified live 2026-10-09 on the same 5 items (HTTP 200)."""
        self.update_listing(external_id, shipping={"free_shipping": True})

    def opt_in_catalog(self, external_id: str, catalog_product_id: str) -> dict[str, Any]:
        """POST /items/catalog_listings. Verified live 2026-10-09: returns
        HTTP 201 with a NEW item id (catalog_listing=true) whose
        item_relations point back at the original, sharing its stock —
        the caller must record that new id so order_sync can map orders
        placed through it."""
        response = self._client.post(
            "/items/catalog_listings",
            headers=self._auth_headers(),
            json={"item_id": external_id, "catalog_product_id": catalog_product_id},
        )
        if response.status_code not in (200, 201):
            raise RuntimeError(
                f"MercadoLibre opt_in_catalog failed ({response.status_code}): {response.text}"
            )
        data: dict[str, Any] = response.json()
        return data

    def get_free_shipping_cost(
        self, item: dict[str, Any], price: Decimal, listing_type_id: str
    ) -> Decimal | None:
        """Real seller-paid cost of offering free shipping on this item at
        this price/listing type, via GET /users/{id}/shipping_options/free
        (all_country.list_cost). Verified live 2026-10-09: 8,000-25,200 COP
        across 5 real items. None when MercadoLibre doesn't return one."""
        params: dict[str, Any] = {
            "item_price": str(price),
            "listing_type_id": listing_type_id,
            "mode": "me2",
            "condition": item.get("condition", "new"),
            "logistic_type": (item.get("shipping") or {}).get("logistic_type") or "xd_drop_off",
        }
        dimensions = (item.get("shipping") or {}).get("dimensions")
        if dimensions:
            params["dimensions"] = dimensions
        else:
            params["item_id"] = item["id"]
        response = self._client.get(
            f"/users/{self._user_id}/shipping_options/free",
            headers=self._auth_headers(),
            params=params,
        )
        if response.status_code != 200:
            logger.warning("shipping_options/free failed for %s: %s", item.get("id"), response.text)
            return None
        cost = ((response.json().get("coverage") or {}).get("all_country") or {}).get("list_cost")
        return None if cost is None else Decimal(str(cost))

    def get_me(self) -> dict[str, Any] | None:
        """GET /users/me — the account itself, incl. seller_reputation."""
        response = self._client.get("/users/me", headers=self._auth_headers())
        if response.status_code != 200:
            return None
        data: dict[str, Any] = response.json()
        return data

    def get_catalog_product(self, catalog_product_id: str) -> dict[str, Any] | None:
        """GET /products/{id} — the catalog product's own name/attributes."""
        response = self._client.get(f"/products/{catalog_product_id}", headers=self._auth_headers())
        if response.status_code != 200:
            return None
        data: dict[str, Any] = response.json()
        return data

    def get_catalog_competitor_prices(self, catalog_product_id: str) -> list[Decimal] | None:
        """Prices of OTHER sellers' active items in this catalog product
        (GET /products/{id}/items), ours excluded. [] when the catalog has
        no active sellers (404 is how MercadoLibre reports that, verified
        2026-10-09); None on any other failure — unknown, not "no
        competition"."""
        response = self._client.get(
            f"/products/{catalog_product_id}/items", headers=self._auth_headers()
        )
        if response.status_code == 404:
            return []
        if response.status_code != 200:
            logger.warning("products/%s/items failed: %s", catalog_product_id, response.text)
            return None
        return sorted(
            Decimal(str(r["price"]))
            for r in response.json().get("results", [])
            if str(r.get("seller_id")) != str(self._user_id)
        )

    def update_stock(self, external_id: str, in_stock: bool) -> None:
        # TODO: PUT /items/{item_id} with {"available_quantity": ...}
        raise NotImplementedError(
            "MercadoLibre update_stock: endpoint not yet verified against real responses."
        )

    def get_orders(self, since: str | None = None) -> list[MarketplaceOrderInfo]:
        """GET /orders/search?seller={user_id}. The real granted OAuth
        scope (urn:ml:mktp:orders-shipments:/read-write) and the response
        envelope ({"results": [...], "paging": {...}}) are verified live —
        but against zero real orders so far (this account has had none),
        so the per-order/order_items field names below are DOC-verified
        only, not live-verified: cross-checked 2026-09-28 against two
        independent mirrors of MercadoLibre's own docs (the docs site
        itself blocks automated fetches) — order.id/.status/
        .date_created/.total_amount/.currency_id/.order_items[].item.id/
        .quantity/.unit_price all agreed between both. Treat this as
        best-effort until it's exercised against a real populated order.

        `since` filters client-side on the real `date_created` field
        rather than an unverified query-param name. Only the first page
        of results is fetched — pagination isn't handled yet (fine while
        real order volume is low; revisit if `paging.total` ever exceeds
        one page)."""
        if not self._authenticated or self._access_token is None or self._user_id is None:
            raise RuntimeError("Call authenticate() before get_orders().")

        response = self._client.get(
            "/orders/search",
            params={"seller": str(self._user_id)},
            headers={"Authorization": f"Bearer {self._access_token}"},
        )
        if response.status_code != 200:
            logger.error("MercadoLibre get_orders failed: %s", response.text)
            raise RuntimeError(
                f"MercadoLibre get_orders failed ({response.status_code}): {response.text}"
            )

        orders: list[MarketplaceOrderInfo] = []
        for raw in response.json().get("results", []):
            date_created = raw.get("date_created")
            if since is not None and date_created is not None and date_created < since:
                continue

            order_items = raw.get("order_items") or []
            first_item = order_items[0] if order_items else {}
            item = first_item.get("item") or {}
            item_id = item.get("id")

            orders.append(
                MarketplaceOrderInfo(
                    external_id=str(raw["id"]),
                    status=raw.get("status", "unknown"),
                    total_amount=Decimal(str(raw.get("total_amount", 0))),
                    currency=raw.get("currency_id", "COP"),
                    item_external_id=str(item_id) if item_id is not None else None,
                    quantity=int(first_item.get("quantity", 1)),
                    raw=raw,
                )
            )
        return orders
