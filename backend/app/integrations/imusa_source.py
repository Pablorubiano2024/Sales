"""Real source adapter for classic-VTEX commerce sites with a real,
documented REST search API — imusa.com.co (Imusa's own direct-sale store)
by default, jumbocolombia.com (`JumboSourceAdapter`) as a second confirmed
site sharing this exact API. Unlike the Falabella-group sites (server-
embedded page JSON), this is VTEX's classic REST search API.

Checked before writing this (Imusa 2026-09-25, Jumbo added same day):
  - robots.txt: imusa.com.co EXPLICITLY allows `/api/catalog_system/` and
    `/*graphql` (and explicitly lists ClaudeBot/Claude-User as allowed
    user agents) — a real, deliberate grant. jumbocolombia.com's
    robots.txt has no `/api/` rule at all (silent, not an explicit
    grant like Imusa's, but also not a denial) under a generally
    permissive default — real product data confirmed reachable the same
    way. Éxito (exito.com) runs the same VTEX platform but its robots.txt
    explicitly DISALLOWS `/api/` — checked the same day — so this
    adapter/pattern must never be pointed at exito.com.
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
# an embedded HTML asset URL, or — confirmed live on Jumbo 2026-09-25 —
# internal metadata fields whose "value" is a serialized JSON blob, not
# human-readable text) — dropped rather than surfaced as "specs".
_NON_SPEC_FIELDS = {"ShortList", "Html", "ProductData", "SkuData"}
# A real spec value is short, human-readable text — a serialized JSON
# blob (Jumbo's ProductData/SkuData) or anything implausibly long is
# never a genuine characteristic, regardless of field name.
_MAX_SPEC_VALUE_LENGTH = 200


def _is_plain_spec_value(value: str) -> bool:
    return len(value) <= _MAX_SPEC_VALUE_LENGTH and not value.lstrip().startswith(("{", "["))


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


class ImusaSourceAdapter(SourceAdapter):
    """Source adapter for imusa.com.co's real, robots.txt-permitted VTEX
    product search API. `base_url` defaults to Imusa itself; subclasses
    (e.g. `JumboSourceAdapter`) or direct callers can point this at any
    confirmed sibling VTEX site sharing this exact classic search API."""

    #: Used only in log messages — cosmetic, but a message that always
    #: says "Imusa" regardless of which real site failed would mislead.
    source_label = "Imusa"

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
            logger.warning(
                "%s product %s has no parseable Price; skipping",
                self.source_label,
                p.get("productId"),
            )
            return None

        list_price = _to_decimal(offer.get("ListPrice"))
        reference_price = list_price if list_price is not None and list_price > price else None

        stock_available = (
            bool(offer.get("IsAvailable")) and (offer.get("AvailableQuantity") or 0) > 0
        )
        image_urls = tuple(img["imageUrl"] for img in item.get("images", []) if img.get("imageUrl"))

        specifications = []
        for name in p.get("allSpecifications") or []:
            if name in _NON_SPEC_FIELDS:
                continue
            values = p.get(name)
            if not values:
                continue
            value = ", ".join(str(v) for v in values)
            if _is_plain_spec_value(value):
                specifications.append((name, value))

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
            specifications=tuple(specifications),
        )

    def _search(self, params: dict[str, str], limit: int = 20) -> list[SourceProductInfo]:
        try:
            response = self._client.get(
                "/api/catalog_system/pub/products/search",
                params={**params, "_from": "0", "_to": str(max(limit - 1, 0))},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("%s search failed (%r): %s", self.source_label, params, exc)
            return []

        try:
            results = response.json()
        except ValueError:
            logger.warning("%s search (%r): response wasn't valid JSON", self.source_label, params)
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
            logger.warning("%s search_products(%r) failed: %s", self.source_label, query, exc)
            return []

        try:
            results = response.json()
        except ValueError:
            logger.warning(
                "%s search_products(%r): response wasn't valid JSON", self.source_label, query
            )
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


class JumboSourceAdapter(ImusaSourceAdapter):
    """Source adapter for jumbocolombia.com — same classic VTEX search API
    as Imusa, confirmed live 2026-09-25 (see module docstring)."""

    source_label = "Jumbo"

    def __init__(
        self,
        base_url: str = "https://www.jumbocolombia.com",
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(base_url=base_url, timeout=timeout, transport=transport)
