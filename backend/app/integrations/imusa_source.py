"""Real source adapter for imusa.com.co — Imusa's own direct-sale online
store, not just a brand that appears on other retailers' catalogs. Unlike
the Falabella-group sites (server-embedded page JSON), this is a classic
VTEX commerce site with a real, documented REST search API.

Checked before writing this (2026-09-25):
  - robots.txt (imusa.com.co/robots.txt) EXPLICITLY allows
    `/api/catalog_system/` and `/*graphql` (and explicitly lists
    ClaudeBot/Claude-User as allowed user agents) — a real, deliberate
    grant, not just an absence of a disallow rule. Éxito (exito.com) runs
    the same VTEX platform but its robots.txt explicitly DISALLOWS
    `/api/` — checked the same day — so this adapter/pattern must never
    be pointed at exito.com.
  - GET /api/catalog_system/pub/products/search/{query}?_from=0&_to={N}
      -> list of VTEX product dicts: {productId, productName, brand, link,
         allSpecifications: [names...], items: [{images: [{imageUrl}],
         sellers: [{commertialOffer: {Price, ListPrice, AvailableQuantity,
         IsAvailable}}]}]}. `_from`/`_to` are a zero-indexed *inclusive*
         range (`_to=49` returns up to 50 items) — a 206 Partial Content
         response for a truncated range is expected, not an error.
  - GET /api/catalog_system/pub/products/search?fq=productId:{id}
      -> same shape, exactly the matching product — used for get_product.
  - `ListPrice` (a real crossed-out reference price) vs `Price` (the live,
    payable price) is the same "real reference price" concept as
    Falabella's `reference_price` — kept only when it's genuinely higher.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from backend.app.core.logging import get_logger
from backend.app.integrations.base import SourceAdapter, SourceProductInfo

logger = get_logger(__name__)

DEFAULT_BASE_URL = "https://www.imusa.com.co"
DEFAULT_TIMEOUT = 15.0
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# Real spec fields VTEX returns alongside genuine product characteristics
# but that aren't real characteristics themselves (marketing copy blocks,
# an embedded HTML asset URL) — dropped rather than surfaced as "specs".
_NON_SPEC_FIELDS = {"ShortList", "Html"}


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


class ImusaSourceAdapter(SourceAdapter):
    """Source adapter for imusa.com.co's real, robots.txt-permitted VTEX
    product search API."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url, timeout=timeout, transport=transport, headers=DEFAULT_HEADERS
        )

    def close(self) -> None:
        self._client.close()

    def _parse_product(self, p: dict[str, Any]) -> SourceProductInfo | None:
        items = p.get("items") or []
        if not items:
            return None
        item = items[0]
        sellers = item.get("sellers") or []
        if not sellers:
            return None
        offer = sellers[0].get("commertialOffer") or {}

        price = _to_decimal(offer.get("Price"))
        if price is None:
            logger.warning("Imusa product %s has no parseable Price; skipping", p.get("productId"))
            return None

        list_price = _to_decimal(offer.get("ListPrice"))
        reference_price = list_price if list_price is not None and list_price > price else None

        stock_available = (
            bool(offer.get("IsAvailable")) and (offer.get("AvailableQuantity") or 0) > 0
        )
        image_urls = tuple(img["imageUrl"] for img in item.get("images", []) if img.get("imageUrl"))

        specifications = tuple(
            (name, ", ".join(str(v) for v in values))
            for name in p.get("allSpecifications") or []
            if name not in _NON_SPEC_FIELDS and (values := p.get(name))
        )

        return SourceProductInfo(
            external_id=str(p["productId"]),
            name=p.get("productName") or f"Product {p.get('productId')}",
            price=price,
            currency="COP",
            stock_available=stock_available,
            url=p.get("link"),
            raw=p,
            reference_price=reference_price,
            image_urls=image_urls,
            brand=p.get("brand") or None,
            specifications=specifications,
        )

    def _search(self, params: dict[str, str], limit: int = 20) -> list[SourceProductInfo]:
        try:
            response = self._client.get(
                "/api/catalog_system/pub/products/search",
                params={**params, "_from": "0", "_to": str(max(limit - 1, 0))},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Imusa search failed (%r): %s", params, exc)
            return []

        try:
            results = response.json()
        except ValueError:
            logger.warning("Imusa search (%r): response wasn't valid JSON", params)
            return []

        products = [self._parse_product(p) for p in results]
        return [p for p in products if p is not None]

    def search_products(self, query: str, limit: int = 20) -> list[SourceProductInfo]:
        try:
            response = self._client.get(
                f"/api/catalog_system/pub/products/search/{query}",
                params={"_from": "0", "_to": str(max(limit - 1, 0))},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Imusa search_products(%r) failed: %s", query, exc)
            return []

        try:
            results = response.json()
        except ValueError:
            logger.warning("Imusa search_products(%r): response wasn't valid JSON", query)
            return []

        products = [self._parse_product(p) for p in results]
        return [p for p in products if p is not None]

    def get_product(self, external_id: str) -> SourceProductInfo | None:
        results = self._search({"fq": f"productId:{external_id}"}, limit=1)
        return results[0] if results else None

    def get_price(self, external_id: str) -> Decimal | None:
        product = self.get_product(external_id)
        return product.price if product else None

    def get_stock(self, external_id: str) -> bool:
        product = self.get_product(external_id)
        return bool(product and product.stock_available)

    def get_product_url(self, external_id: str) -> str | None:
        product = self.get_product(external_id)
        return product.url if product else None
