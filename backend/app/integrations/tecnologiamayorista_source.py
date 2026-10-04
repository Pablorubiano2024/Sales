"""Real source adapter for tecnologiamayorista.com — a real Colombian
wholesale ("mayorista") electronics/small-appliance distributor, found
while looking for a domestic (not international, unlike CJdropshipping)
source genuinely cheaper than big-box retail (Alkosto/Falabella/
Ktronix/Homecenter are all consumer retail price, the same tier most
real MercadoLibre sellers already buy at or below).

Checked before writing this (2026-10-04):
  - robots.txt explicitly allows all crawlers (`Allow: /`) and even
    documents a UCP/MCP agent-commerce endpoint — this storefront is
    deliberately built to be bot/agent-friendly, not just tolerant of it.
  - Real Shopify storefront. Two real, public, unauthenticated JSON
    endpoints used here (no admin API, no login):
      - GET /search/suggest.json?q=<text>&resources[type]=product&
        resources[limit]=<n> -> real predictive-search results, each
        with `id`, `handle`, `title`, `price`, `compare_at_price_max`,
        `available`, `vendor`, `tags`, `image`/`featured_image`, and
        `body` (an HTML description that embeds real "Label: value"
        spec bullets, e.g. "Tipo: Freidora de aire digital"). Capped at
        10 results regardless of a higher `resources[limit]`.
      - GET /products.json?limit=<n>&page=<n> -> paginated full catalog,
        same real shape (confirmed: each variant has `available`).
    `GET /products/{handle}.json` (the classic single-product detail
    endpoint) is ALSO real and public, but does NOT expose `available`
    at all (confirmed live) — so `get_product` deliberately never uses
    it; it re-runs the same predictive search with the handle's own
    words as the query and picks the exact handle match instead, one
    real call, always with real stock.
  - Real, deliberate two-tier pricing: the same physical product is
    often listed TWICE as separate "products" — a consumer-facing one
    and a "... B2B" (handle suffix `-b2b`) one at a real, lower
    wholesale price (confirmed live: a Xiaomi air fryer at $399,900
    B2C vs $325,000 B2B; a Sokany air fryer at $199,900 vs $170,000).
    Both are real, independent listings here — never merged/guessed
    into one "the real price is X" value.
  - `vendor` is uniformly "Tecnologia Mayorista" (the store's own name),
    NOT the product's real brand (Xiaomi, Sokany, Winning Star...) —
    there is no separate structured brand field, so `brand` is always
    None here rather than regex-guessed from the title. The real brand
    usually IS visible in the free-text title/specs themselves, which
    `listing_draft_service`'s own category-attribute matching can still
    pick up from `specifications`.
  - Real, fairly aggressive per-IP rate limiting observed live (plain
    `429` body `"local_rate_limited"`, no Retry-After header seen) —
    `_get_with_retry` below backs off and retries a few times rather
    than treat a single 429 as fatal.
"""

from __future__ import annotations

import html
import re
import time
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from backend.app.core.logging import get_logger
from backend.app.integrations.base import SourceAdapter, SourceProductInfo

logger = get_logger(__name__)

DEFAULT_BASE_URL = "https://www.tecnologiamayorista.com"
DEFAULT_TIMEOUT = 15.0
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}
# Shopify's predictive search caps results regardless of a higher
# resources[limit] — confirmed live.
MAX_SEARCH_RESULTS = 10
RATE_LIMIT_RETRY_SECONDS = 20.0
MAX_RATE_LIMIT_RETRIES = 3
# Same real word-overlap safety check used by catalog_lookup.py /
# alkosto_source.py — a fuzzy storefront search can still surface a
# plausible-looking but wrong accessory for a verbose query.
_MIN_TOKEN_OVERLAP_RATIO = 0.5

_SPEC_LINE_RE = re.compile(r"<li[^>]*>(.*?)</li>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _normalize_tokens(text: str) -> set[str]:
    stripped = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return set(re.findall(r"[a-z0-9]+", stripped.lower()))


def _is_plausible_match(query: str, candidate_name: str) -> bool:
    query_tokens = _normalize_tokens(query)
    if not query_tokens:
        return False
    candidate_tokens = _normalize_tokens(candidate_name)
    overlap = len(query_tokens & candidate_tokens) / len(query_tokens)
    return overlap >= _MIN_TOKEN_OVERLAP_RATIO


def _to_decimal(raw: Any) -> Decimal | None:
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        return None


def _extract_specifications(body_html: str) -> tuple[tuple[str, str], ...]:
    """Real "Label: value" bullets embedded in the product's own
    description HTML (see module docstring) — never invented; a bullet
    with no literal colon, or an empty side, is just skipped."""
    specs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_li in _SPEC_LINE_RE.findall(body_html):
        text = html.unescape(_TAG_RE.sub("", raw_li)).strip()
        if ":" not in text:
            continue
        name, _, value = text.partition(":")
        name, value = name.strip(), value.strip()
        if not name or not value or name in seen:
            continue
        seen.add(name)
        specs.append((name, value))
    return tuple(specs)


class TecnologiaMayoristaSourceAdapter(SourceAdapter):
    """Source adapter for tecnologiamayorista.com's real, public Shopify
    storefront search API."""

    source_label = "Tecnologia Mayorista"

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

    def _search(self, query: str, limit: int) -> list[dict[str, Any]]:
        params = {
            "q": query,
            "resources[type]": "product",
            "resources[limit]": str(min(limit, MAX_SEARCH_RESULTS)),
        }
        response = self._client.get("/search/suggest.json", params=params)
        attempt = 0
        while response.status_code == 429 and attempt < MAX_RATE_LIMIT_RETRIES:
            time.sleep(RATE_LIMIT_RETRY_SECONDS)
            response = self._client.get("/search/suggest.json", params=params)
            attempt += 1
        try:
            response.raise_for_status()
            return response.json()["resources"]["results"]["products"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            logger.warning("%s search(%r) failed: %s", self.source_label, query, exc)
            return []

    def _parse_result(self, item: dict[str, Any]) -> SourceProductInfo | None:
        price = _to_decimal(item.get("price"))
        if price is None:
            logger.warning(
                "%s product %s has no parseable price; skipping",
                self.source_label,
                item.get("handle"),
            )
            return None

        compare_at = _to_decimal(item.get("compare_at_price_max") or item.get("compare_at_price"))
        reference_price = compare_at if compare_at is not None and compare_at > price else None

        image = item.get("featured_image") or item.get("image") or {}
        image_url = image.get("url") if isinstance(image, dict) else None

        return SourceProductInfo(
            external_id=str(item["handle"]),
            name=item.get("title", f"Product {item.get('handle')}"),
            price=price,
            currency="COP",
            stock_available=bool(item.get("available", False)),
            url=f"{self._client.base_url}/products/{item['handle']}",
            raw=None,
            reference_price=reference_price,
            image_urls=(image_url,) if image_url else (),
            brand=None,
            specifications=_extract_specifications(item.get("body") or ""),
        )

    def search_products(self, query: str, limit: int = 20) -> list[SourceProductInfo]:
        results = self._search(query, limit)
        products = []
        for item in results:
            if not _is_plausible_match(query, item.get("title", "")):
                continue
            parsed = self._parse_result(item)
            if parsed is not None:
                products.append(parsed)
        return products[:limit]

    def get_product(self, external_id: str) -> SourceProductInfo | None:
        query = external_id.replace("-", " ")
        results = self._search(query, MAX_SEARCH_RESULTS)
        match = next((item for item in results if item.get("handle") == external_id), None)
        if match is None:
            return None
        return self._parse_result(match)

    def get_price(self, external_id: str) -> Decimal | None:
        product = self.get_product(external_id)
        return product.price if product else None

    def get_stock(self, external_id: str) -> bool:
        product = self.get_product(external_id)
        return bool(product and product.stock_available)

    def get_product_url(self, external_id: str) -> str | None:
        return f"{self._client.base_url}/products/{external_id}"
