"""Real MercadoLibre category prediction + required-attribute check.

Both endpoints are public (no auth needed) — verified live 2026-09-22:
  - GET /sites/MCO/domain_discovery/search?q=<free text>
      -> list of {domain_id, domain_name, category_id, category_name,
         attributes}, ordered by relevance.
  - GET /categories/{category_id}/attributes
      -> list of attribute dicts with `id`, `name`, `tags: {required, ...}`.

Used by scripts/publish_approved_opportunities.py to decide, per product,
whether it's safe to auto-publish. `create_listing()` always supplies
BRAND and MODEL (see mercadolibre.py) — a category that requires anything
else (e.g. POWER_SUPPLY_TYPE) has no real per-product value available at
mass-publish time and must be skipped for manual review rather than
guessing one.
"""

from __future__ import annotations

import httpx

from backend.app.core.logging import get_logger

logger = get_logger(__name__)

API_BASE_URL = "https://api.mercadolibre.com"
DEFAULT_TIMEOUT = 15.0
SAFE_ATTRIBUTE_IDS = {"BRAND", "MODEL"}


def predict_category(query: str, *, client: httpx.Client) -> str | None:
    """Best-guess category_id for a free-text product name, or None if
    domain_discovery returned nothing / the call failed."""
    try:
        response = client.get("/sites/MCO/domain_discovery/search", params={"q": query})
        response.raise_for_status()
        results = response.json()
    except httpx.HTTPError as exc:
        logger.warning("domain_discovery(%r) failed: %s", query, exc)
        return None
    if not results:
        return None
    category_id = results[0].get("category_id")
    return str(category_id) if category_id else None


def required_attribute_ids(category_id: str, *, client: httpx.Client) -> list[str]:
    try:
        response = client.get(f"/categories/{category_id}/attributes")
        response.raise_for_status()
        attributes = response.json()
    except httpx.HTTPError as exc:
        logger.warning("categories/%s/attributes failed: %s", category_id, exc)
        return []
    return [a["id"] for a in attributes if (a.get("tags") or {}).get("required")]


def is_safe_to_autopublish(category_id: str, *, client: httpx.Client) -> bool:
    """True when every required attribute for this category is one
    create_listing() already supplies (BRAND, MODEL)."""
    required = required_attribute_ids(category_id, client=client)
    return set(required) <= SAFE_ATTRIBUTE_IDS
