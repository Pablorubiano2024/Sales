"""Real MercadoLibre category prediction + required-attribute check.

`predict_category`/`list_attributes` are public (no auth needed) —
verified live 2026-09-22:
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

`get_sale_commission_pct` (verified live 2026-09-25) hits the same
`/sites/MCO/listing_prices` endpoint used elsewhere, but it now requires
auth (`403 PA_UNAUTHORIZED_RESULT_FROM_POLICIES` without a bearer token —
this wasn't true earlier in the same week, so don't assume it stays
public). The real "Clásica" (gold_special) commission is category-
specific, not the flat estimate `Settings.marketplace_commission_pct`
assumed — confirmed live: 16.5% for MCO456045 (Freidoras) vs 12.0% for
MCO118449 (Relojes), both flat across price points within the category.

Real bug found live 2026-10-01: `tags.required` isn't the only tag that
can block a real publish — MCO456045's real GTIN attribute has
`tags.required: false` but `tags.conditional_required: true`, and a real
create_listing attempt for a real Freidora Electrolux failed with
`item.attribute.missing_conditional_required` (GTIN, a barcode we have no
real source for) even though `is_safe_to_autopublish` had said yes.
`required_attribute_ids` now also treats `conditional_required` as
blocking — conservative on purpose: we don't know the exact condition
that triggers it per category, so this never risks guessing a GTIN.

Real gap found 2026-10-03: with `is_safe_to_autopublish` only ever
allowing BRAND/MODEL, a live dry run against production skipped 73 of 74
real "approved" opportunities — almost every real category (TVs,
neveras, lavadoras, aspiradoras, cafeteras...) requires at least one
attribute beyond brand/model, and this blocked ALL of them even when the
source's real specifications already had a confident match for that
exact attribute. `is_safe_to_autopublish` now takes `extra_covered_ids`
so a caller that already ran `match_specifications` for this product can
let a required attribute through when it was actually matched.

Checking the same dry run's remaining skips against MercadoLibre's own
public `/categories/{id}/attributes` directly (2026-10-03) showed the
REAL universal blocker isn't category-specific attributes at all — it's
GTIN (`conditional_required` on every one of 6 real categories checked:
TVs, neveras, lavadoras, parlantes, microondas, freidoras), which no
retail source ever gives us. MercadoLibre's schema makes `EMPTY_GTIN_REASON`
look like a real, honest way out — a `list` attribute with a value id
(`17055160`, "El producto no tiene código registrado") that reads like
exactly our situation — so this was tried: supply
`{"id": "EMPTY_GTIN_REASON", "value_id": "17055160"}` instead of a real
GTIN. **A real `--confirm` publish attempt against category MCO11860
(2026-10-03) proved this wrong**: MercadoLibre rejected it with the
exact same `item.attribute.missing_conditional_required` error, citing
GTIN specifically, EMPTY_GTIN_REASON having made no difference. So GTIN
is a genuinely hard requirement wherever it's conditional_required —
`is_safe_to_autopublish` never treats it as coverable, and no
`gtin_exemption_attribute`-style helper exists here anymore; don't
re-add one without a real, different, live-confirmed submission shape
(e.g. the error message's own hint about variation-level attributes,
untested here).

Checking the same failed real response confirmed a second fix WAS
correct: GRADING (also `conditional_required` on most of the same
categories) was never mentioned in that 400 — only GTIN was — matching
the theory that GRADING's own `new_hidden: true` tag means MercadoLibre
genuinely doesn't require it for a `condition="new"` item, the only
condition create_listing() here ever publishes.
`required_attribute_ids` excludes any `new_hidden` attribute for that
reason.

The user then asked to investigate declaring GTIN "at the variation
level" (per the real error message's own hint). That led somewhere
better: MercadoLibre has a real, public (no auth), per-item endpoint —
`POST /categories/{id}/attributes/conditional` with
`{"condition": "new", "attributes": [{"id": "BRAND", ...}, {"id":
"MODEL", ...}]}` -> `{"required_attributes": [...]}` — that resolves
conditional_required attributes FOR REAL, given the actual brand/model,
instead of guessing from the static schema. Confirmed live 2026-10-03
this is genuinely brand+category-specific, not a blanket per-category
flag: GTIN came back required for Electrolux/Samsung/Whirlpool/LG/TCL/
JBL on freidoras-with-that-one-brand/neveras/TVs/parlantes, but NOT
required for KALLEY/IMUSA/Haceb/Acros/a made-up generic brand on
freidoras/aspiradoras/lavadoras/cafeteras — and not even for LG on
freidoras specifically (so it's not "well-known brand" either, it's
genuinely this specific brand+category pair, almost certainly tied to
how many real GTINs that brand already has on file in that category,
per MercadoLibre's own docs). GRADING never came back required either,
independently confirming the `new_hidden` fix above was right.

`required_attribute_ids`/`is_safe_to_autopublish` now call this real
endpoint (`real_conditional_required_ids`) whenever a real brand/model
are available, instead of treating every `conditional_required`
attribute as always-blocking. This is a genuine improvement over the
2026-10-01 fix's "conservative on purpose" stance — that was actually
just wrong for most of our real brands, not conservative; the real
per-item check is the actual ground truth, not a guess. GTIN still
blocks real listings for the specific brand/category pairs where
MercadoLibre's own check says it's required (Electrolux freidoras,
anything-TVs/neveras/parlantes) — no workaround for that is known.
"""

from __future__ import annotations

import unicodedata
from decimal import Decimal
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


def real_conditional_required_ids(
    category_id: str, *, brand: str, model: str, client: httpx.Client
) -> list[str] | None:
    """Ask MercadoLibre's own real per-item check
    (`POST /categories/{id}/attributes/conditional`, public, no auth —
    confirmed live 2026-10-03) which `conditional_required` attributes
    actually apply to this exact brand/model, instead of guessing from
    the static schema. Always sends `condition: "new"` — the only
    condition create_listing() here ever publishes. Returns None (not an
    empty list — "we don't know" is not "nothing required") on any HTTP
    error, so callers fall back to treating every conditional_required
    attribute as blocking rather than silently trust an empty result."""
    try:
        response = client.post(
            f"/categories/{category_id}/attributes/conditional",
            json={
                "condition": "new",
                "attributes": [
                    {"id": "BRAND", "value_name": brand},
                    {"id": "MODEL", "value_name": model},
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as exc:
        logger.warning(
            "categories/%s/attributes/conditional(brand=%r, model=%r) failed: %s",
            category_id,
            brand,
            model,
            exc,
        )
        return None
    return [a["id"] for a in data.get("required_attributes") or []]


def required_attribute_ids(
    category_id: str,
    *,
    client: httpx.Client,
    brand: str | None = None,
    model: str | None = None,
) -> list[str]:
    """Attribute ids that would block a real publish for this specific
    item: plainly `required` attributes (always, from the static
    schema), plus whichever `conditional_required` attributes are
    actually required for this exact brand/model per
    `real_conditional_required_ids` — confirmed live 2026-10-03 this is
    genuinely brand+category-specific (GTIN required for Electrolux
    freidoras, not for KALLEY/IMUSA/generic-brand freidoras; required for
    every brand checked on TVs/neveras/parlantes), so treating every
    conditional_required attribute as a blanket "always blocks" (the
    2026-10-01 fix) was wrong, not conservative. Falls back to that old
    blanket behavior only when `brand`/`model` aren't given yet, or the
    real check call itself fails — never silently assumes nothing is
    required. `new_hidden` attributes (e.g. GRADING) are excluded
    outright: MercadoLibre doesn't apply them to a `condition="new"`
    item, and that's the only condition create_listing() here ever
    publishes — independently confirmed by the same real per-item check
    never returning GRADING as required."""
    try:
        response = client.get(f"/categories/{category_id}/attributes")
        response.raise_for_status()
        attributes = response.json()
    except httpx.HTTPError as exc:
        logger.warning("categories/%s/attributes failed: %s", category_id, exc)
        return []

    not_new_hidden = [a for a in attributes if not (a.get("tags") or {}).get("new_hidden")]
    plain_required = [a["id"] for a in not_new_hidden if (a.get("tags") or {}).get("required")]
    conditional_ids = {
        a["id"] for a in not_new_hidden if (a.get("tags") or {}).get("conditional_required")
    }

    if not conditional_ids:
        return plain_required
    if brand is None or model is None:
        return [*plain_required, *conditional_ids]

    really_required = real_conditional_required_ids(
        category_id, brand=brand, model=model, client=client
    )
    if really_required is None:
        return [*plain_required, *conditional_ids]
    return [*plain_required, *(conditional_ids & set(really_required))]


def is_safe_to_autopublish(
    category_id: str,
    *,
    client: httpx.Client,
    brand: str | None = None,
    model: str | None = None,
    extra_covered_ids: frozenset[str] = frozenset(),
) -> bool:
    """True when every required attribute for this category/item is
    either one create_listing() already supplies (BRAND, MODEL) or one
    the caller has already confirmed it can fill with a real, matched
    value — `extra_covered_ids` is meant to be the attribute ids
    `match_specifications` actually matched for this specific product
    (never a blanket "this category has a match_specifications entry
    somewhere" check). Pass the real `brand`/`model` so
    `required_attribute_ids` can resolve conditional attributes (GTIN,
    GRADING, ...) against this exact item rather than guessing — see
    module docstring for what that changed live."""
    required = required_attribute_ids(category_id, client=client, brand=brand, model=model)
    return set(required) <= (SAFE_ATTRIBUTE_IDS | extra_covered_ids)


def get_sale_commission_pct(
    category_id: str,
    price: Decimal,
    *,
    client: httpx.Client,
    access_token: str,
    listing_type_id: str = "gold_special",
) -> Decimal | None:
    """Real sale commission (as a fraction, e.g. 0.165) for this exact
    category/price/listing_type — requires auth (see module docstring).
    None if the lookup fails or that listing_type_id isn't offered here;
    callers should fall back to `Settings.marketplace_commission_pct`
    rather than guess a specific number."""
    try:
        response = client.get(
            "/sites/MCO/listing_prices",
            params={"price": str(price), "category_id": category_id},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        options = response.json()
    except httpx.HTTPError as exc:
        logger.warning("listing_prices(category=%s, price=%s) failed: %s", category_id, price, exc)
        return None

    option = next(
        (o for o in options if isinstance(o, dict) and o.get("listing_type_id") == listing_type_id),
        None,
    )
    if option is None or price <= 0:
        return None
    sale_fee = option.get("sale_fee_amount")
    if sale_fee is None:
        return None
    return (Decimal(str(sale_fee)) / price).quantize(Decimal("0.0001"))


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


# A handful of confirmed real-world name mismatches between Falabella's
# spec labels and MercadoLibre's attribute names for the same concept
# (checked live 2026-09-25 against category MCO118449 — smartwatches).
# Used only as a fallback when no exact name match exists, and only ever
# applied to an attribute id that's actually present (with a compatible
# value_type) in the category being published to — so this being generic
# across categories is harmless, not just watch-specific.
_KNOWN_SYNONYMS: dict[str, str] = {
    "material de la correa": "WRISTBAND_MATERIAL",
    "color principal de la correa": "WRISTBAND_COLOR",
    "conexion bluetooth": "WITH_BLUETOOTH",
}


def _match_bounded_value(attr: dict[str, Any], raw_value: str) -> str | None:
    """When the attribute has a real, bounded `values` list (a controlled
    vocabulary, even for value_type "string"/"boolean" — e.g.
    WRISTBAND_MATERIAL only accepts 6 real material names), return the
    list's own canonical name on an exact case-insensitive match, else
    None. When there's no bounded list at all, the raw value is accepted
    as free text."""
    values = attr.get("values")
    if not values:
        return raw_value
    normalized = _normalize(raw_value)
    for v in values:
        if _normalize(v["name"]) == normalized:
            return str(v["name"])
    return None


def match_specifications(
    category_id: str, specifications: tuple[tuple[str, str], ...], *, client: httpx.Client
) -> list[dict[str, str]]:
    """Map a source's real (name, value) spec pairs onto this category's
    real attributes — first by an exact, normalized name match (e.g.
    Falabella's "Tipo de pantalla" -> MercadoLibre's attribute of the same
    name), then by a small curated synonym table for confirmed real
    mismatches (see _KNOWN_SYNONYMS). Deliberately conservative:
      - Only `value_type` "string" or "boolean" (a `number_unit`/"list"
        attribute needs a structured {number, unit} shape or a specific
        value_id this can't safely guess from free text).
      - Never hidden, read-only, or multivalued (submission shape for
        multiple values isn't confirmed here) attributes.
      - Never BRAND/MODEL/ITEM_CONDITION (create_listing's own params).
      - When the attribute has a real bounded value list (many "string"
        attributes do, e.g. WRISTBAND_MATERIAL), the source's value must
        match one of those real options exactly (accent/case-insensitive)
        or it's skipped — never sent as a guessed free-text value.
    No fuzzy name matching — a near-miss name is treated as no match
    rather than risk sending the wrong value."""
    if not specifications:
        return []

    attributes = list_attributes(category_id, client=client)
    eligible = {
        a["id"]: a
        for a in attributes
        if a.get("value_type") in ("string", "boolean")
        and a["id"] not in _HANDLED_ELSEWHERE
        and not (a.get("tags") or {}).get("hidden")
        and not (a.get("tags") or {}).get("read_only")
        and not (a.get("tags") or {}).get("multivalued")
    }
    by_name = {_normalize(a["name"]): a["id"] for a in eligible.values()}

    matched: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for spec_name, spec_value in specifications:
        normalized_name = _normalize(spec_name)
        attr_id = by_name.get(normalized_name) or _KNOWN_SYNONYMS.get(normalized_name)
        if attr_id is None or attr_id in seen_ids or attr_id not in eligible:
            continue
        value = _match_bounded_value(eligible[attr_id], spec_value)
        if value is None:
            continue
        matched.append({"id": attr_id, "value_name": value})
        seen_ids.add(attr_id)
    return matched
