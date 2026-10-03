"""Real MercadoLibre catalog product lookup + Buy Box data — the data
source for the Market Gap Scanner (Autopilot Phase 4).

Both endpoints require a bearer token (confirmed live 2026-09-28:
`/products/search` needs one, same tightening already seen on
`/sites/MCO/listing_prices` in category_lookup.py).

Critical live finding (2026-09-28, checked against 3 real
catalog_product_ids for actual iPhone 15 listings, each with 14-24 real
competing sellers): `GET /products/{id}`'s own `buy_box_winner` field is
NOT a reliable signal — it came back `null` for every one of them despite
the real competition. The only reliable source for seller_count/winning
price/seller is `GET /products/{id}/items`:
  - 200 -> {"paging": {"total": N, ...}, "results": [{"item_id",
    "seller_id", "price", "currency_id", ...}, ...]} — `results` is
    ML-ranked, `results[0]` is the current Buy Box winner (verified
    against real response bodies, not the docs — MercadoLibre's docs site
    blocks automated fetches).
  - 404 -> {"message": "No winners found", "error": "not_found", ...}
    when there are zero active competing listings for that catalog
    product (already known from a prior session's live check).
This module never reads `buy_box_winner` for that reason — it is real
data, just not a reliable one for this purpose.

Publishing a listing IN catalog mode (`catalog_listing`/`catalog_product_id`
on POST /items) is deliberately NOT implemented here — that write payload
shape hasn't been verified against a real response (an actual write test
would create a real, public listing), so it stays out of scope until it
can be confirmed. The scanner below only ever reads.

Second critical live finding (2026-09-28, checked against real production
product names): `/products/search`'s top result is NOT reliably the right
product for our verbose, marketing-heavy product names. A real example:
searching our own "Licuadora Ninja Sistema Profesional de Cocina
Inteligente 1700 W Auto." top-matched catalog_product_id MCO54625550,
whose real name is "Ninja 6 Navajas 72oz Aspa Cuchilla Licuadora Aspas
Para Licuadora Ninja Repuestos..." — a REPLACEMENT BLADE, not the
blender — which would have fed completely wrong Buy Box data (a $129,900
accessory price) into an opportunity actually priced at $1,199,900.
`find_catalog_product` below rejects a match whose name doesn't share
enough real words with the query (see `_MIN_TOKEN_OVERLAP_RATIO`) rather
than trust a plausible-looking but wrong catalog_product_id.

Real finding 2026-10-03 (chasing why GTIN blocks real brands like LG/
Samsung/TCL but not KALLEY/IMUSA — see category_lookup.py's docstring):
some real `/products/search` results already carry a real, manufacturer-
registered `GTIN` attribute with one or more real barcode values (e.g.
a real "Parlante LG XBOOM Go" search result's GTIN had
`value_name: "8806098242597, 719192620131, 8806098297139"`) — this is
genuine data, not something to guess. The product DETAIL endpoint
(`GET /products/{id}`) does NOT expose this same attribute, only the
search result does, so `find_catalog_gtin` reads it from a fresh
`/products/search` call rather than from `find_catalog_product`'s
already-fetched result (kept as two separate single-purpose calls,
matching this module's existing style, rather than threading one
result through both). NOT yet confirmed whether supplying this real
value actually satisfies a real `create_listing` GTIN requirement —
MercadoLibre's own `/categories/{id}/attributes/conditional` check
(category_lookup.py) returns the identical "GTIN required" result
regardless of what's passed for GTIN, so it can't validate this; only a
real publish attempt can.
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from backend.app.core.logging import get_logger

logger = get_logger(__name__)

API_BASE_URL = "https://api.mercadolibre.com"
DEFAULT_TIMEOUT = 15.0
# MercadoLibre returned a real (if terse) {"message":"local_rate_limited"}
# 429 on a cold first call during live verification (2026-09-28) — retry
# a couple of times with a short backoff rather than treat it as fatal.
RATE_LIMIT_RETRY_SECONDS = 5.0
MAX_RATE_LIMIT_RETRIES = 2
# At least this fraction of the query's real words must appear in the
# candidate's real name — tuned against two real examples checked live
# 2026-09-28: a wrong accessory match shared 2/10 words (0.2, correctly
# rejected) and a borderline-plausible-but-still-wrong "display" part
# match shared 3/6 (0.5, also correctly rejected at this threshold).
_MIN_TOKEN_OVERLAP_RATIO = 0.6


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


def _get_with_retry(
    client: httpx.Client, path: str, *, params: dict[str, str] | None, headers: dict[str, str]
) -> httpx.Response:
    response = client.get(path, params=params, headers=headers)
    attempt = 0
    while response.status_code == 429 and attempt < MAX_RATE_LIMIT_RETRIES:
        time.sleep(RATE_LIMIT_RETRY_SECONDS)
        response = client.get(path, params=params, headers=headers)
        attempt += 1
    return response


def find_catalog_product(query: str, *, client: httpx.Client, access_token: str) -> str | None:
    """Best-guess real catalog_product_id for a free-text product name, via
    GET /products/search?site_id=MCO&q=<text> (verified live: real
    catalog_product_id values, e.g. "MCO27172667" for a real iPhone 15).
    None if nothing matched, the top result doesn't plausibly name the
    same product (see module docstring — this is a real, confirmed
    failure mode, not a hypothetical one), or the call failed."""
    try:
        response = _get_with_retry(
            client,
            "/products/search",
            params={"site_id": "MCO", "q": query},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        results = response.json().get("results", [])
    except httpx.HTTPError as exc:
        logger.warning("products/search(%r) failed: %s", query, exc)
        return None
    if not results:
        return None

    top = results[0]
    candidate_name = top.get("name", "")
    if not _is_plausible_match(query, candidate_name):
        logger.info(
            "products/search(%r) top result %r doesn't plausibly match — skipping",
            query,
            candidate_name,
        )
        return None

    catalog_product_id = top.get("catalog_product_id") or top.get("id")
    return str(catalog_product_id) if catalog_product_id else None


def find_catalog_gtin(query: str, *, client: httpx.Client, access_token: str) -> str | None:
    """A real, manufacturer-registered GTIN MercadoLibre's own catalog
    already has on file for this product, if any (see module docstring
    for a confirmed real example) — never a guessed/fabricated barcode.
    None when nothing plausibly matches (same rule as
    `find_catalog_product`) or the top match has no real GTIN on file —
    that's a genuine "we don't have one", not a failure to try harder."""
    try:
        response = _get_with_retry(
            client,
            "/products/search",
            params={"site_id": "MCO", "q": query},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        results = response.json().get("results", [])
    except httpx.HTTPError as exc:
        logger.warning("products/search(%r) failed: %s", query, exc)
        return None
    if not results:
        return None

    top = results[0]
    if not _is_plausible_match(query, top.get("name", "")):
        return None

    gtin_attribute = next((a for a in top.get("attributes") or [] if a.get("id") == "GTIN"), None)
    if gtin_attribute is None:
        return None
    values = gtin_attribute.get("values") or []
    if not values:
        return None
    gtin = values[0].get("name")
    return str(gtin) if gtin else None


@dataclass(frozen=True, slots=True)
class BuyBoxSnapshot:
    seller_count: int
    buy_box_price: Decimal | None
    buy_box_seller_id: str | None
    stock_available: bool


def get_buy_box_snapshot(
    catalog_product_id: str, *, client: httpx.Client, access_token: str
) -> BuyBoxSnapshot | None:
    """Real Buy Box state for a catalog product via
    GET /products/{id}/items (see module docstring for why not
    buy_box_winner). None only on an unexpected error — a real "no active
    sellers" state is BuyBoxSnapshot(seller_count=0, ...), not None."""
    try:
        response = _get_with_retry(
            client,
            f"/products/{catalog_product_id}/items",
            params=None,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    except httpx.HTTPError as exc:
        logger.warning("products/%s/items failed: %s", catalog_product_id, exc)
        return None

    if response.status_code == 404:
        return BuyBoxSnapshot(
            seller_count=0, buy_box_price=None, buy_box_seller_id=None, stock_available=False
        )
    if response.status_code != 200:
        logger.warning(
            "products/%s/items failed (%s): %s",
            catalog_product_id,
            response.status_code,
            response.text,
        )
        return None

    data: dict[str, Any] = response.json()
    results = data.get("results", [])
    seller_count = data.get("paging", {}).get("total", len(results))
    if not results:
        return BuyBoxSnapshot(
            seller_count=seller_count,
            buy_box_price=None,
            buy_box_seller_id=None,
            stock_available=seller_count > 0,
        )
    winner = results[0]
    return BuyBoxSnapshot(
        seller_count=seller_count,
        buy_box_price=Decimal(str(winner["price"])),
        buy_box_seller_id=str(winner["seller_id"]),
        stock_available=True,
    )
