"""Real HTTP-based source adapter backed by DummyJSON (https://dummyjson.com).

This is a genuine, working `SourceAdapter` implementation — it makes real
HTTP requests, parses real JSON, and handles real network/HTTP failures
(timeouts, 404s, connection errors) gracefully instead of raising.

IMPORTANT — this is NOT a real Colombian supplier. DummyJSON is a public,
unauthenticated demo/sandbox product API (no signup required) commonly used
to build and test e-commerce integrations. Prices are fictional and in USD;
`pricing_engine` does not perform currency conversion, so opportunities
built from this source should not be mixed with COP-denominated marketplace
prices for real decisions. It exists to prove out the real-HTTP-integration
pattern (base URL, timeouts, error handling, response parsing) so a real
supplier (e.g. Dropi, once an account/integration key is available — see
PROJECT_CONTEXT.md) can be dropped in later without touching callers.

Verified against the live API before writing this (2026-09-17):
  GET https://dummyjson.com/products/search?q={query}&limit={n}
      -> {"products": [{id, title, price, stock, sku, availabilityStatus,
                         category, brand, images: [...]}, ...]}
  GET https://dummyjson.com/products/{id}
      -> the same single product shape, or 404 if not found.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from backend.app.core.logging import get_logger
from backend.app.integrations.base import SourceAdapter, SourceProductInfo

logger = get_logger(__name__)

DEFAULT_BASE_URL = "https://dummyjson.com"
DEFAULT_TIMEOUT = 10.0


class DummyJsonSourceAdapter(SourceAdapter):
    """Source adapter for the public DummyJSON product catalog (demo data)."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        # `transport` is a testing seam (e.g. httpx.MockTransport) so unit
        # tests can exercise this adapter without a real network call.
        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def _parse_product(self, item: dict[str, Any]) -> SourceProductInfo | None:
        try:
            price = Decimal(str(item["price"]))
        except (KeyError, InvalidOperation):
            logger.warning(
                "DummyJSON product %s has an unparseable price; skipping", item.get("id")
            )
            return None

        external_id = str(item["id"])
        stock = item.get("stock", 0)
        availability = item.get("availabilityStatus", "")

        return SourceProductInfo(
            external_id=external_id,
            name=item.get("title", f"Product {external_id}"),
            price=price,
            currency="USD",
            stock_available=bool(stock) and availability != "Out of Stock",
            url=self.get_product_url(external_id),
            raw=item,
        )

    def search_products(self, query: str, limit: int = 20) -> list[SourceProductInfo]:
        try:
            response = self._client.get("/products/search", params={"q": query, "limit": limit})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("DummyJSON search_products('%s') failed: %s", query, exc)
            return []

        items = response.json().get("products", [])
        products = [self._parse_product(item) for item in items]
        return [p for p in products if p is not None]

    def get_product(self, external_id: str) -> SourceProductInfo | None:
        try:
            response = self._client.get(f"/products/{external_id}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("DummyJSON get_product('%s') failed: %s", external_id, exc)
            return None

        return self._parse_product(response.json())

    def get_price(self, external_id: str) -> Decimal | None:
        product = self.get_product(external_id)
        return product.price if product else None

    def get_stock(self, external_id: str) -> bool:
        product = self.get_product(external_id)
        return bool(product and product.stock_available)

    def get_product_url(self, external_id: str) -> str | None:
        base = str(self._client.base_url).rstrip("/")
        return f"{base}/products/{external_id}"
