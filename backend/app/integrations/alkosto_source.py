"""Real source adapter for Alkosto (alkosto.com) and Ktronix (ktronix.com)
— two separately-branded Colombian electronics/appliance retailers that
turn out to share one real backend: both run on SAP Commerce Cloud
(confirmed live via the `x-sap-pad` response header and a
`ROUTE=.accstorefront-...` cookie on every response) and the SAME real
catalog — product id 195950797978 (a real iPad Air SKU) resolves to the
identical name/price on both sites, confirmed live 2026-10-02.

Checked before writing this (2026-10-02):
  - robots.txt on both sites EXPLICITLY disallows `/search/` and any
    `?q=` query string (their own search-results page), unlike the
    Falabella-group/VTEX adapters — this module never queries a real
    search endpoint. Common SAP Commerce OCC REST paths (`/rest/v2/...`,
    `/occ/v2/...`) were probed live and returned 404 — not exposed
    publicly on either site.
  - robots.txt DOES explicitly list `Sitemap: .../sitemap-productos.xml`
    (31k real URLs on alkosto.com, ~9k on ktronix.com, ~1.5s to fetch) —
    a real, deliberate crawl grant. `search_products` uses this instead:
    fetched once per adapter instance (lazily, cached in-memory) to build
    a {slug tokens -> product id} index, matched against the query via
    the same word-overlap technique `catalog_lookup.find_catalog_product`
    uses for MercadoLibre, just inverted (every query token must appear
    in the slug, since here the query is the generic/short side and the
    slug is the specific one). This means `search_products` costs 1
    sitemap fetch (first call only) + up to `limit` real page fetches —
    heavier than the other adapters' single request, and limited to
    whatever vocabulary the real URL slugs happen to use — confirmed live:
    a real TV's slug is "tv-tcl-55-pulgadas-..." (matching query "tv"),
    while "television"/"televisor" match almost nothing. A genuine
    limitation of matching on slugs instead of a real search index, not
    something to paper over with stemming we haven't verified — pick
    query terms confirmed against the real sitemap vocabulary (see the
    discover_alkosto.py/discover_ktronix.py QUERIES lists).
  - GET /x/p/{numeric_id} (any throwaway slug text) -> real 301 to the
    canonical slug URL, confirmed live for both sites — so `get_product`
    never needs to know the real slug, only the id from the sitemap.
  - The product detail page embeds real schema.org microdata directly in
    server-rendered HTML (no JSON blob like the Falabella/VTEX adapters):
    `<h1 itemprop="name">`, a self-contained `<div itemprop="offers"
    itemscope itemtype=".../Offer">` block with `price`/`priceCurrency`/
    `availability` (schema.org/InStock when real stock exists), and a
    separate `<div itemprop="brand" itemtype=".../Brand"><meta
    itemprop="name" content="APPLE"/></div>`. The crossed-out reference
    price, when a real discount is active, is in
    `#js-original_price_old .before-price__basePrice` — kept only when it
    parses to a value strictly above the live price (same rule as
    Falabella's `reference_price`). The real `itemprop="image"` meta tag
    has a confirmed site bug (the CDN url is concatenated onto the
    site's own domain, e.g. "https://www.alkosto.comhttps://cdn.dam...")
    on both sites, so this adapter uses the clean `og:image` meta tag
    instead. No specifications table was found in the static HTML (the
    "especificaciones" panel appears to be client-rendered) — left as ()
    rather than guessed.
"""

from __future__ import annotations

import html
import re
import unicodedata
from decimal import Decimal, InvalidOperation

import httpx

from backend.app.core.logging import get_logger
from backend.app.integrations.base import SourceAdapter, SourceProductInfo

logger = get_logger(__name__)

DEFAULT_BASE_URL = "https://www.alkosto.com"
DEFAULT_TIMEOUT = 15.0
# The real sitemap-productos.xml is ~16MB on alkosto.com (~5MB on
# ktronix.com) — the default timeout above is tuned for ordinary product
# pages, not this.
SITEMAP_TIMEOUT = 30.0
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

_SITEMAP_LOC_RE = re.compile(r"<loc>(https://[^<]+?/p/(\d+))</loc>")
_OFFER_BODY_RE = re.compile(
    r'itemprop="offers"[^>]*itemtype="https://schema\.org/Offer"[^>]*>'
    r"(?P<body>.*?)"
    r'itemprop="seller"',
    re.DOTALL,
)
_PRICE_RE = re.compile(r'itemprop="price" content="([^"]+)"')
_CURRENCY_RE = re.compile(r'itemprop="priceCurrency" content="([^"]+)"')
_AVAILABILITY_RE = re.compile(r'itemprop="availability" href="https://schema\.org/([A-Za-z]+)"')
_NAME_RE = re.compile(r'<h1 class="js-main-title" itemprop="name">([^<]+)')
_BRAND_RE = re.compile(
    r'itemprop="brand"[^>]*itemtype="https://schema\.org/Brand"[^>]*>'
    r'\s*<meta itemprop="name" content="([^"]*)"'
)
_BASE_PRICE_RE = re.compile(r'before-price__basePrice">\s*\$?\s*([0-9.,]+)')
_OG_IMAGE_RE = re.compile(r'<meta property="og:image" content="([^"]+)"')


def _to_decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.strip())
    except InvalidOperation:
        return None


def _parse_cop_price(raw: str) -> Decimal | None:
    """ "4.709.010" (period thousands separators, no decimals) -> Decimal."""
    digits = re.sub(r"[^\d]", "", raw)
    if not digits:
        return None
    try:
        return Decimal(digits)
    except InvalidOperation:
        return None


def _normalize_tokens(text: str) -> frozenset[str]:
    stripped = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return frozenset(re.findall(r"[a-z0-9]+", stripped.lower()))


# Real filler words seen in this project's own discovery query lists (e.g.
# "freidora de aire") that never survive into a real URL slug — dropped
# from the query side before matching, never from the slug side.
_QUERY_STOPWORDS = frozenset({"de", "la", "el", "los", "las", "y", "en", "con", "para", "del"})


class AlkostoSourceAdapter(SourceAdapter):
    """Source adapter for alkosto.com's real SAP Commerce storefront.
    `base_url` defaults to Alkosto itself; `KtronixSourceAdapter` points
    this at the confirmed sibling site sharing the same catalog/platform."""

    #: Used only in log messages, to say which real site a failure was
    #: against — cosmetic, but a message that always said "Alkosto" for
    #: Ktronix too would be misleading.
    source_label = "Alkosto"

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
        )
        # Lazily built on first search_products() call — see module
        # docstring ("search_products uses this instead").
        self._catalog_index: list[tuple[frozenset[str], str]] | None = None

    def close(self) -> None:
        self._client.close()

    def _fetch_catalog_index(self) -> list[tuple[frozenset[str], str]]:
        try:
            response = self._client.get("/sitemap-productos.xml", timeout=SITEMAP_TIMEOUT)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("%s: failed to fetch sitemap-productos.xml: %s", self.source_label, exc)
            return []

        entries = []
        for match in _SITEMAP_LOC_RE.finditer(response.text):
            url, product_id = match.group(1), match.group(2)
            slug = url.rsplit("/p/", 1)[0]
            entries.append((_normalize_tokens(slug), product_id))
        logger.info(
            "%s: indexed %d real product URLs from sitemap-productos.xml",
            self.source_label,
            len(entries),
        )
        return entries

    def _ensure_catalog_index(self) -> list[tuple[frozenset[str], str]]:
        if self._catalog_index is None:
            self._catalog_index = self._fetch_catalog_index()
        return self._catalog_index

    def search_products(self, query: str, limit: int = 20) -> list[SourceProductInfo]:
        query_tokens = _normalize_tokens(query) - _QUERY_STOPWORDS
        if not query_tokens:
            return []

        matched_ids: list[str] = []
        seen_ids: set[str] = set()
        for slug_tokens, product_id in self._ensure_catalog_index():
            if product_id in seen_ids:
                continue
            if query_tokens <= slug_tokens:
                matched_ids.append(product_id)
                seen_ids.add(product_id)
                if len(matched_ids) >= limit:
                    break

        products = [self.get_product(pid) for pid in matched_ids]
        return [p for p in products if p is not None]

    def get_product(self, external_id: str) -> SourceProductInfo | None:
        try:
            # Any slug text works — the real site 301-redirects a bare id
            # to the canonical slug URL (see module docstring).
            response = self._client.get(f"/x/p/{external_id}")
            if response.status_code == 404:
                return None
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("%s get_product(%r) failed: %s", self.source_label, external_id, exc)
            return None

        page = response.text
        offer_match = _OFFER_BODY_RE.search(page)
        if offer_match is None:
            logger.warning(
                "%s get_product(%r): no offers microdata found", self.source_label, external_id
            )
            return None
        body = offer_match.group("body")

        price_match = _PRICE_RE.search(body)
        price = _to_decimal(price_match.group(1)) if price_match else None
        if price is None:
            logger.warning(
                "%s get_product(%r): unparseable/missing price", self.source_label, external_id
            )
            return None

        currency_match = _CURRENCY_RE.search(body)
        currency = currency_match.group(1) if currency_match else "COP"

        availability_match = _AVAILABILITY_RE.search(body)
        stock_available = availability_match is not None and availability_match.group(1) == (
            "InStock"
        )

        name_match = _NAME_RE.search(page)
        name = (
            html.unescape(name_match.group(1).strip()) if name_match else f"Product {external_id}"
        )

        brand_match = _BRAND_RE.search(page)
        brand = (brand_match.group(1).strip() or None) if brand_match else None

        reference_price = None
        base_price_match = _BASE_PRICE_RE.search(page)
        if base_price_match is not None:
            base_price = _parse_cop_price(base_price_match.group(1))
            if base_price is not None and base_price > price:
                reference_price = base_price

        og_image_match = _OG_IMAGE_RE.search(page)
        image_urls: tuple[str, ...] = (og_image_match.group(1),) if og_image_match else ()

        return SourceProductInfo(
            external_id=external_id,
            name=name,
            price=price,
            currency=currency,
            stock_available=stock_available,
            url=str(response.url),
            raw=None,
            reference_price=reference_price,
            image_urls=image_urls,
            brand=brand,
        )

    def get_price(self, external_id: str) -> Decimal | None:
        product = self.get_product(external_id)
        return product.price if product else None

    def get_stock(self, external_id: str) -> bool:
        product = self.get_product(external_id)
        return bool(product and product.stock_available)

    def get_product_url(self, external_id: str) -> str | None:
        product = self.get_product(external_id)
        return product.url if product else None


class KtronixSourceAdapter(AlkostoSourceAdapter):
    """Source adapter for ktronix.com — same SAP Commerce platform and the
    same real catalog as Alkosto, confirmed live 2026-10-02 (see module
    docstring)."""

    source_label = "Ktronix"

    def __init__(
        self,
        base_url: str = "https://www.ktronix.com",
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(base_url=base_url, timeout=timeout, transport=transport)
