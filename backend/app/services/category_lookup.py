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

import unicodedata
from typing import Any

import httpx

from backend.app.core.logging import get_logger

logger = get_logger(__name__)

API_BASE_URL = "https://api.mercadolibre.com"
DEFAULT_TIMEOUT = 15.0
SAFE_ATTRIBUTE_IDS = {"BRAND", "MODEL"}
# Attribute ids already handled by dedicated create_listing() params —
# never re-add them via matched specifications.
_HANDLED_ELSEWHERE = {"BRAND", "MODEL", "ITEM_CONDITION"}


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


def _normalize(name: str) -> str:
    """Case/accent-insensitive comparison key ("Tamaño" == "tamano")."""
    stripped = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return stripped.strip().lower()


def list_attributes(category_id: str, *, client: httpx.Client) -> list[dict[str, Any]]:
    try:
        response = client.get(f"/categories/{category_id}/attributes")
        response.raise_for_status()
        result: list[dict[str, Any]] = response.json()
        return result
    except httpx.HTTPError as exc:
        logger.warning("categories/%s/attributes failed: %s", category_id, exc)
        return []


def match_specifications(
    category_id: str, specifications: tuple[tuple[str, str], ...], *, client: httpx.Client
) -> list[dict[str, str]]:
    """Map a source's real (name, value) spec pairs onto this category's
    real attributes by an exact, normalized name match — e.g. Falabella's
    "Tamaño de la pantalla" -> MercadoLibre's DISPLAY_SIZE attribute of
    the same name. Deliberately conservative: only free-text (`value_type
    == "string"`) attributes are matched (a "list"/`number_unit` attribute
    needs a specific value_id or structured {number, unit} shape this
    can't safely guess), never hidden/read-only ones, and never BRAND/
    MODEL/ITEM_CONDITION (already handled by create_listing's own params).
    No fuzzy matching — a near-miss name is treated as no match rather
    than risk sending the wrong value."""
    if not specifications:
        return []

    attributes = list_attributes(category_id, client=client)
    by_name = {
        _normalize(a["name"]): a["id"]
        for a in attributes
        if a.get("value_type") == "string"
        and a["id"] not in _HANDLED_ELSEWHERE
        and not (a.get("tags") or {}).get("hidden")
        and not (a.get("tags") or {}).get("read_only")
    }

    matched: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for spec_name, spec_value in specifications:
        attr_id = by_name.get(_normalize(spec_name))
        if attr_id is None or attr_id in seen_ids:
            continue
        matched.append({"id": attr_id, "value_name": spec_value})
        seen_ids.add(attr_id)
    return matched
