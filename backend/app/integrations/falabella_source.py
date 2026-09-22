"""Real source adapter for falabella.com.co — NOT an official API (Falabella
doesn't offer a public product API to individual sellers), but a genuine,
verified data source: falabella.com.co is a Next.js app that embeds full,
structured product data (name, brand, prices, stock) as JSON in a
`<script id="__NEXT_DATA__">` tag on both search and product pages — a
plain unauthenticated GET + JSON parse, no headless browser needed.

Checked before writing this (2026-09-22):
  - robots.txt (falabella.com.co/robots.txt) allows all crawlers except
    account/checkout/basket/orders paths, which this adapter never touches.
  - GET /falabella-co/search?Ntt={query}
      -> __NEXT_DATA__.props.pageProps.results: list of {productId,
         displayName, brand, url, prices: [{type, price: ["1.234.567"],
         crossed}, ...]}. Prices are Colombian-formatted strings
         (period thousands separators, no decimals) — not JSON numbers.
  - GET /falabella-co/product/{id}  (slug is optional — the bare numeric
    id resolves and redirects correctly)
      -> __NEXT_DATA__.props.pageProps.productData: {id, name, brandName,
         isOutOfStock, prices (top-level, same shape as search), variants}.

Search results don't carry a reliable stock signal (their `availability`
field is always empty) — only the product detail page's `isOutOfStock`
does, so `search_products` defaults `stock_available=True` and callers
needing an accurate stock check should use `get_stock`/`get_product`.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from backend.app.core.logging import get_logger
from backend.app.integrations.base import SourceAdapter, SourceProductInfo

logger = get_logger(__name__)

DEFAULT_BASE_URL = "https://www.falabella.com.co"
DEFAULT_TIMEOUT = 15.0
# A plain httpx User-Agent gets served meaningfully different (JS-shell-only)
# content on some pages — a realistic desktop UA is what was verified live.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)


def _extract_next_data(html: str) -> dict[str, Any] | None:
    match = _NEXT_DATA_RE.search(html)
    if match is None:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return None


def _parse_cop_price(raw: str) -> Decimal | None:
    """ "2.149.900" (period thousands separators, no decimals) -> Decimal."""
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        return None
    try:
        return Decimal(digits)
    except InvalidOperation:
        return None


def _best_price(prices: list[dict[str, Any]]) -> Decimal | None:
    """Prefer the live "internetPrice" entry; fall back to whatever's first."""
    by_type = {p.get("type"): p for p in prices}
    entry = by_type.get("internetPrice") or (prices[0] if prices else None)
    if entry is None:
        return None
    values = entry.get("price") or []
    if not values:
        return None
    return _parse_cop_price(values[0])


def _reference_price(prices: list[dict[str, Any]]) -> Decimal | None:
    """The crossed-out "normalPrice" (the real, non-discounted list price)
    — real market data, not a guess. None when there's no active discount
    (no normalPrice entry, or it doesn't actually exceed the live price)."""
    by_type = {p.get("type"): p for p in prices}
    entry = by_type.get("normalPrice")
    if entry is None:
        return None
    values = entry.get("price") or []
    if not values:
        return None
    normal = _parse_cop_price(values[0])
    live = _best_price(prices)
    if normal is None or live is None or normal <= live:
        return None
    return normal


class FalabellaSourceAdapter(SourceAdapter):
    """Source adapter for falabella.com.co's embedded product JSON."""

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

    def __enter__(self) -> FalabellaSourceAdapter:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _parse_search_result(self, item: dict[str, Any]) -> SourceProductInfo | None:
        prices = item.get("prices") or []
        price = _best_price(prices)
        if price is None:
            logger.warning(
                "Falabella product %s has an unparseable/missing price; skipping",
                item.get("productId"),
            )
            return None

        return SourceProductInfo(
            external_id=str(item["productId"]),
            name=item.get("displayName", f"Product {item.get('productId')}"),
            price=price,
            currency="COP",
            # Search results carry no reliable stock signal (see module
            # docstring) — assume available; use get_stock for a real check.
            stock_available=True,
            url=item.get("url"),
            raw=item,
            reference_price=_reference_price(prices),
        )

    def search_products(self, query: str, limit: int = 20) -> list[SourceProductInfo]:
        try:
            response = self._client.get("/falabella-co/search", params={"Ntt": query})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Falabella search_products('%s') failed: %s", query, exc)
            return []

        data = _extract_next_data(response.text)
        if data is None:
            logger.warning("Falabella search_products('%s'): no __NEXT_DATA__ found", query)
            return []

        results = data.get("props", {}).get("pageProps", {}).get("results", [])
        products = [self._parse_search_result(item) for item in results[:limit]]
        return [p for p in products if p is not None]

    def get_product(self, external_id: str) -> SourceProductInfo | None:
        try:
            response = self._client.get(f"/falabella-co/product/{external_id}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Falabella get_product('%s') failed: %s", external_id, exc)
            return None

        data = _extract_next_data(response.text)
        if data is None:
            logger.warning("Falabella get_product('%s'): no __NEXT_DATA__ found", external_id)
            return None

        product = data.get("props", {}).get("pageProps", {}).get("productData")
        if product is None:
            return None

        prices = product.get("prices") or []
        price = _best_price(prices)
        if price is None:
            # Top-level productData doesn't always carry prices; the active
            # variant's do (see module docstring — "variants").
            variants = product.get("variants") or []
            current = str(product.get("currentVariant", ""))
            variant = next((v for v in variants if str(v.get("id")) == current), None)
            if variant is not None:
                prices = variant.get("prices") or []
                price = _best_price(prices)
        if price is None:
            logger.warning("Falabella get_product('%s'): unparseable/missing price", external_id)
            return None

        return SourceProductInfo(
            external_id=external_id,
            name=product.get("name", f"Product {external_id}"),
            price=price,
            currency="COP",
            reference_price=_reference_price(prices),
            stock_available=not product.get("isOutOfStock", False),
            url=str(response.url),
            raw=product,
        )

    def get_price(self, external_id: str) -> Decimal | None:
        product = self.get_product(external_id)
        return product.price if product else None

    def get_stock(self, external_id: str) -> bool:
        product = self.get_product(external_id)
        return bool(product and product.stock_available)

    def get_product_url(self, external_id: str) -> str | None:
        base = str(self._client.base_url).rstrip("/")
        return f"{base}/falabella-co/product/{external_id}"
