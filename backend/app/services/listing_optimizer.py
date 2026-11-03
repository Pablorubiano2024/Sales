"""Listing Optimizer — one general rule applied to every active MercadoLibre
listing, instead of tuning them one by one (explicit user decision,
2026-10-09: "lo que no quiero es hacer esto producto por producto, desde
que nos aseguremos que cubre costos y gastos y queda ganancia apliquemos
algo general para todos los productos").

The single hard constraint, checked with REAL numbers for every change:
at the final price, after the real category-specific sale commission and
the real seller-paid free-shipping cost, the listing must still clear
Settings.min_roi AND Settings.min_net_profit. Nothing below that "floor"
price is ever applied.

Per active listing:
  1. Exposure — a "free" listing is upgraded to "Clásica" (gold_special)
     with free shipping. Verified live 2026-10-09: free listings had 0-7
     visits in 2+ weeks; free listings also can't offer free shipping.
  2. Price —
     - catalog competitors known (GET /products/{id}/items, ours
       excluded): price just under the cheapest one (CATALOG_UNDERCUT),
       which can also RAISE the price when we were needlessly far below.
       If even the floor can't beat them, the listing is paused (it can't
       compete profitably — same call the user approved for the Xiaomi
       Watch 5 Active on 2026-10-09).
     - no confirmed competitor: keep the current price (raised to the
       floor if it fell below it). Never lowered on an estimate alone.
     Either way never below the floor.
  3. Catalog — if MercadoLibre tags the item `catalog_listing_eligible`
     and it's verifiably the same product (`catalog_matches`), opt it in
     (a new, stock-linked item; recorded as its own MarketplaceProduct so
     order_sync maps its orders).

LAUNCH MODE — while the account has fewer than LAUNCH_MODE_MAX_SALES
completed sales (seller_reputation.transactions.completed). Verified live
2026-10-13: our catalog item was 16% cheaper than the only competitor and
still lost the Buy Box with reason `reputation_below_threshold`, and 4
days of Clásica + free shipping brought visits (Imusa 7.5L 93 -> 125) but
zero sales. Until reputation exists the Buy Box is unwinnable, so:
every listing is priced AT the floor (cheapest price that still clears
MIN_ROI / MIN_NET_PROFIT — the user's own rule, 2026-10-13: "lo que
consideres más óptimo", no paid Product Ads), still paused when a
same-product competitor is cheaper than that floor, and no new catalog
opt-ins — except for an item tagged `catalog_forewarning`: MercadoLibre
pauses those unless they join the catalog (emailed "avisos próximos a
pausarse", 2026-10-21, both Xiaomi Redmi Watch 6), so opting in at the
same ROI-cleared price beats losing the listing. Switches back to normal
mode on its own after those first sales. A forewarned item reactivated
without opting in goes straight to `under_review` until it does
(2026-11-01, Redmi Watch 6), and the opt-in brings it back
(`awaits_catalog_opt_in`).

HANDLING TIME — every listing gets MercadoLibre's "tiempo de disponibilidad"
(mercadolibre.HANDLING_TIME), whatever else is skipped below: the source
store has to deliver to us before we can dispatch.

BUY SOURCE — always the listing's ORIGIN source (the one its SKU was
built from, `origin_source`), never another source discovery attached to
the same product: checked 2026-10-15, those cross-source matches are
often a different item (easychef55 <- a Tezzio 4L, Holstein 9L <- a
Haceb). It must have been re-checked by the sync within MAX_SOURCE_AGE,
be in stock and approved/promising (`buy_source_blocker`), otherwise no
changes.

REACTIVATION — a listing WE paused (sub_status `paused_by_seller`) goes
through the same rule and is switched back on when everything holds:
it has a buy source as above, still has MercadoLibre stock, no other
live listing of ours sells the same product (same product row or same
catalog product — MercadoLibre penalizes duplicates; the Imusa Mega 7.5L
and Esencial 3.2L each have a paused twin), and the price decision clears
the floor (no same-product competitor below it).
Same gate as an active listing, so a pause is no longer one-way
(2026-10-15: Quick 3.5L, 2nd most visited, stayed off after a one-off
source fetch failure; Digital 8L's buy price dropped 359,900 -> 199,900
while it sat paused).

`decide_price`, `minimum_profitable_price`, `buy_source_blocker` and
`reactivation_blocker` are pure; `optimize_listing` does the real I/O
and only writes when `apply=True`.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.core.logging import get_logger
from backend.app.core.time import utcnow
from backend.app.integrations.mercadolibre import (
    HANDLING_TIME,
    MercadoLibreAdapter,
    with_handling_time,
)
from backend.app.jobs.discovery import build_sku
from backend.app.models.marketplace import ListingCatalogMatch, ListingStatus, MarketplaceProduct
from backend.app.models.opportunity import Opportunity, OpportunityStatus
from backend.app.models.source import Source, SourceProduct
from backend.app.services import category_lookup, listing_service
from backend.app.services.product_matcher import name_numbers, name_variants

logger = get_logger(__name__)

TARGET_LISTING_TYPE = "gold_special"
# Price this fraction under the cheapest catalog competitor.
CATALOG_UNDERCUT = Decimal("0.01")
MAX_FLOOR_ITERATIONS = 8
LAUNCH_MODE_MAX_SALES = 5
GENERIC_MODEL = "Genérico"


def round_price_up(price: Decimal) -> Decimal:
    """Next "...900" price at or above `price` (COP retail convention)."""
    thousands = ((price + 100) / 1000).to_integral_value(rounding=ROUND_CEILING)
    return thousands * 1000 - 100


def round_price_down(price: Decimal) -> Decimal:
    """Previous "...900" price at or below `price`."""
    thousands = ((price + 100) / 1000).to_integral_value(rounding=ROUND_FLOOR)
    return thousands * 1000 - 100


def net_profit(
    price: Decimal, buy: Decimal, fee: Decimal, ship: Decimal, other: Decimal
) -> Decimal:
    return price - buy - fee - ship - other


def required_profit(buy: Decimal, min_roi: Decimal, min_net: Decimal) -> Decimal:
    return max(buy * min_roi, min_net)


def minimum_profitable_price(
    buy: Decimal,
    other_costs: Decimal,
    fee_for: Callable[[Decimal], Decimal],
    ship_for: Callable[[Decimal], Decimal],
    min_roi: Decimal,
    min_net: Decimal,
) -> Decimal:
    """Lowest "...900" price whose real net profit clears both thresholds.
    Fee and shipping depend on the price itself, so iterate upward until
    stable (both only grow with price, so this converges)."""
    needed = required_profit(buy, min_roi, min_net)
    price = round_price_up(buy + other_costs + needed)
    for _ in range(MAX_FLOOR_ITERATIONS):
        candidate = round_price_up(buy + other_costs + needed + fee_for(price) + ship_for(price))
        if candidate <= price:
            return price
        price = candidate
    return price


@dataclass
class PriceDecision:
    action: str  # "price", "pause" or (decide_publish_price) "skip"
    price: Decimal | None
    reason: str


def decide_price(
    floor: Decimal,
    current_price: Decimal,
    competitor_prices: list[Decimal] | None,
    *,
    launch_mode: bool = False,
) -> PriceDecision:
    if competitor_prices:
        cheapest = competitor_prices[0]
        under = round_price_down(cheapest * (1 - CATALOG_UNDERCUT))
        if under >= cheapest:
            under = round_price_down(cheapest - 1000)
        if under < floor:
            return PriceDecision(
                "pause",
                None,
                f"competidor más barato {cheapest:,.0f} < precio mínimo rentable {floor:,.0f}",
            )
        if launch_mode:
            return PriceDecision("price", floor, "lanzamiento: precio mínimo rentable")
        return PriceDecision(
            "price", under, f"justo debajo del competidor más barato ({cheapest:,.0f})"
        )
    if launch_mode:
        return PriceDecision("price", floor, "lanzamiento: precio mínimo rentable")
    if current_price >= floor:
        return PriceDecision("price", current_price, "sin competencia confirmada: se mantiene")
    return PriceDecision("price", floor, "precio actual bajo el mínimo rentable: se sube al mínimo")


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    stripped = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return "".join(ch for ch in stripped.lower() if ch.isalnum())


def _attr(attributes: list[dict] | None, attr_id: str) -> str | None:
    for attr in attributes or []:
        if attr.get("id") == attr_id:
            return attr.get("value_name")
    return None


def catalog_matches(item: dict, catalog_product: dict) -> bool:
    """Is MercadoLibre's suggested catalog product really OUR product?
    Guards both catalog opt-in and competitor-based pricing. Real cases
    (2026-10-09): our Redmi Watch 6 *Lite* (1.96") was suggested the plain
    Redmi Watch 6 (2.07") — a different product; our Galaxy Watch 8's
    MODEL is the manufacturer code while the catalog's is the commercial
    name — the same product. So: same MODEL, or same brand + same numbers
    in the name (size/capacity/version) + same variant words.

    An item tagged `catalog_forewarning` is one MercadoLibre itself
    already identified with this catalog product (and will pause unless
    it joins), so the catalog's shorter name only has to have no number
    ours lacks (2026-10-21: "Redmi Watch 6 Blue" for our "Redmi Watch 6
    Pantalla Amoled De 2.07"). Brand and variant words must still match,
    so a Lite is never taken for the plain model."""
    our_model = _normalize(_attr(item.get("attributes"), "MODEL"))
    their_model = _normalize(_attr(catalog_product.get("attributes"), "MODEL"))
    if our_model and our_model == their_model:
        return True
    our_brand = _normalize(_attr(item.get("attributes"), "BRAND"))
    their_brand = _normalize(_attr(catalog_product.get("attributes"), "BRAND"))
    if not our_brand or our_brand != their_brand:
        return False
    title, name = item.get("title"), catalog_product.get("name")
    if name_variants(title) != name_variants(name):
        return False
    if "catalog_forewarning" in (item.get("tags") or []):
        return name_numbers(name) <= name_numbers(title)
    return name_numbers(title) == name_numbers(name)


@dataclass
class OptimizationResult:
    external_id: str
    title: str
    actions: list[str] = field(default_factory=list)
    skipped: str | None = None
    paused: bool = False
    reactivated: bool = False


MAX_SOURCE_AGE = timedelta(hours=36)
VIABLE_STATUSES = {OpportunityStatus.APPROVED, OpportunityStatus.PROMISING}


def buy_source_blocker(
    opportunity: Opportunity | None, source_product: SourceProduct | None, now: datetime
) -> str | None:
    """Why the origin source can't be priced from right now, or None."""
    if opportunity is None or source_product is None:
        return "sin fuente de origen"
    if not source_product.stock_available:
        return "fuente de origen sin stock"
    checked = source_product.last_checked_at
    if checked is None or now - checked > MAX_SOURCE_AGE:
        return "fuente de origen sin revisar hoy"
    if opportunity.status not in VIABLE_STATUSES:
        return f"oportunidad '{opportunity.status.value}'"
    return None


def listing_keys(product_id: str, item: dict) -> set[str]:
    """What makes two of our listings "the same product"."""
    keys = {f"product:{product_id}"}
    if item.get("catalog_product_id"):
        keys.add(f"catalog:{item['catalog_product_id']}")
    return keys


def reactivation_blocker(item: dict, keys: set[str], live_keys: set[str]) -> str | None:
    """Why a paused item must stay paused regardless of price, or None.
    Only pauses we made — or a sell-out (`out_of_stock`: its last unit
    sold, first sale 2026-10-22; reactivation restocks it) — are ours to
    undo, and never into a duplicate."""
    sub_status = item.get("sub_status")
    if sub_status == ["out_of_stock"]:
        pass
    elif sub_status != ["paused_by_seller"]:
        return f"pausado por MercadoLibre ({sub_status})"
    elif not item.get("available_quantity"):
        return "sin stock en MercadoLibre"
    if keys & live_keys:
        return "ya hay otro aviso activo del mismo producto"
    return None


def completed_sales(ml: MercadoLibreAdapter) -> int | None:
    """Real completed-sales count from the account's own seller
    reputation (GET /users/me). None if MercadoLibre doesn't return it."""
    me = ml.get_me()
    if me is None:
        return None
    transactions = (me.get("seller_reputation") or {}).get("transactions") or {}
    completed = transactions.get("completed")
    return int(completed) if completed is not None else None


def is_launch_mode(ml: MercadoLibreAdapter) -> bool:
    """Unknown sales count counts as launch — the safer (cheaper, still
    profitable) side when we can't tell."""
    sales = completed_sales(ml)
    return sales is None or sales < LAUNCH_MODE_MAX_SALES


def should_opt_in_catalog(item: dict, *, launch_mode: bool) -> bool:
    """Eligible, not already a catalog item, and either past launch mode
    or forewarned (MercadoLibre will pause it otherwise)."""
    tags = item.get("tags") or []
    return (
        (not launch_mode or "catalog_forewarning" in tags)
        and "catalog_listing_eligible" in tags
        and not item.get("catalog_listing")
        and not item.get("item_relations")
    )


def origin_source(
    db: Session, listing: MarketplaceProduct
) -> tuple[Opportunity | None, SourceProduct | None]:
    """The source this listing's product was discovered at (its SKU is
    built from it), with its Opportunity for this marketplace."""
    product = listing.product
    for source_product in db.query(SourceProduct).filter_by(product_id=product.id):
        source = db.get(Source, source_product.source_id)
        if (
            source is not None
            and source_product.external_id
            and build_sku(source.name, source_product.external_id) == product.sku
        ):
            opportunity = (
                db.query(Opportunity)
                .filter_by(
                    product_id=product.id,
                    source_id=source.id,
                    marketplace_id=listing.marketplace_id,
                )
                .first()
            )
            return opportunity, source_product
    return None, None


def awaits_catalog_opt_in(item: dict) -> bool:
    """Inactive until it joins the catalog, not for anything we can fix on
    the item itself."""
    return item.get("status") == "under_review" and "catalog_forewarning" in (
        item.get("tags") or []
    )


def catalog_rescue_blocker(
    decision: PriceDecision, current: Decimal, floor: Decimal, *, can_opt_in: bool
) -> str | None:
    """It opts in at its current price; only the next run can change that."""
    if decision.action == "pause":
        return decision.reason
    if current < floor:
        return f"precio actual {current:,.0f} < precio mínimo rentable {floor:,.0f}"
    if not can_opt_in:
        return "no se pudo verificar que el catálogo sugerido sea el mismo producto"
    return None


def is_origin_opportunity(db: Session, opportunity: Opportunity) -> bool:
    """Is this the source the product row is ours from? A row can also hold
    other sources' items that only looked similar, so publishing from one of
    them lists a product the row's buy source doesn't sell (2026-10-31: the
    Imusa 10-speed from Alkosto on the row of Ktronix's 12-speed)."""
    source = db.get(Source, opportunity.source_id)
    source_product = (
        db.query(SourceProduct)
        .filter_by(source_id=opportunity.source_id, product_id=opportunity.product_id)
        .first()
    )
    if source is None or source_product is None or not source_product.external_id:
        return False
    return build_sku(source.name, source_product.external_id) == opportunity.product.sku


def find_identical_catalog_product(
    ml: MercadoLibreAdapter, title: str, brand: str, model: str
) -> dict | None:
    """The first catalog product that passes `catalog_matches` for this
    not-yet-published product, searched by brand + model, then by full
    name. None when none is verifiably the same."""
    has_model = model != GENERIC_MODEL
    item = {
        "title": title,
        "attributes": [
            {"id": "BRAND", "value_name": brand},
            *([{"id": "MODEL", "value_name": model}] if has_model else []),
        ],
    }
    queries = [f"{brand} {model}", title] if has_model else [title]
    for query in queries:
        for catalog_product in ml.search_catalog_products(query):
            if catalog_matches(item, catalog_product):
                return catalog_product
    return None


def find_market_prices(
    ml: MercadoLibreAdapter,
    title: str,
    brand: str,
    model: str,
    *,
    finder: Callable[[str, str, str], dict | None] | None = None,
) -> list[Decimal] | None:
    """Other sellers' real prices for this exact product, before it's
    published (see `find_identical_catalog_product`; `finder` lets a caller
    reuse one it already looked up). None when no catalog product is
    verifiably the same; [] when it has no other sellers."""
    catalog_product = (
        finder(title, brand, model)
        if finder is not None
        else find_identical_catalog_product(ml, title, brand, model)
    )
    if catalog_product is None:
        return None
    return ml.get_catalog_competitor_prices(catalog_product["id"])


def decide_publish_price(
    floor: Decimal, competitor_prices: list[Decimal] | None, *, launch_mode: bool
) -> PriceDecision:
    """Publish only at a price backed by real competitors: the listing's
    first price used to be the source's list price or a 1.8x estimate
    (2026-10-31: a TV bought at 4.1M would have gone up at 15M; the Hamilton
    Beach coffee maker went up at 790,900 and was paused against a 665,000
    competitor). Same pricing as a live listing; action "skip" = no publish."""
    if not competitor_prices:
        return PriceDecision("skip", None, "sin precio real de competidores")
    decision = decide_price(floor, floor, competitor_prices, launch_mode=launch_mode)
    return decision if decision.action == "price" else PriceDecision("skip", None, decision.reason)


def _competitor_prices(ml: MercadoLibreAdapter, catalog_ids: set[str]) -> list[Decimal] | None:
    """Other sellers' prices across every catalog product known to be
    ours. None when there's none to check, or any lookup failed
    (unknown, not "no competition")."""
    if not catalog_ids:
        return None
    prices: list[Decimal] = []
    for catalog_id in sorted(catalog_ids):
        found = ml.get_catalog_competitor_prices(catalog_id)
        if found is None:
            return None
        prices.extend(found)
    return sorted(prices)


def _opt_in(
    db: Session,
    ml: MercadoLibreAdapter,
    listing: MarketplaceProduct,
    catalog_product_id: str,
    price: Decimal,
) -> None:
    assert listing.external_id is not None
    created = ml.opt_in_catalog(listing.external_id, catalog_product_id)
    db.add(
        MarketplaceProduct(
            marketplace_id=listing.marketplace_id,
            product_id=listing.product_id,
            external_id=created["id"],
            url=created.get("permalink"),
            selling_price=Decimal(str(created.get("price", price))),
            currency=listing.currency,
            status=ListingStatus.ACTIVE,
        )
    )
    db.commit()


def optimize_listing(
    db: Session,
    ml: MercadoLibreAdapter,
    listing: MarketplaceProduct,
    settings: Settings,
    *,
    apply: bool,
    launch_mode: bool = False,
    live_keys: set[str] | None = None,
) -> OptimizationResult:
    """`live_keys` — listing_keys of every listing already live; process
    ACTIVE listings first so paused twins see them. Updated in place when
    this one is (re)activated."""
    if live_keys is None:
        live_keys = set()
    assert listing.external_id is not None
    info = ml.get_listing(listing.external_id)
    if info is None or info.raw is None:
        return OptimizationResult(listing.external_id, "?", skipped="no existe en MercadoLibre")
    item = info.raw
    result = OptimizationResult(listing.external_id, item.get("title", "")[:50])
    awaiting_catalog = awaits_catalog_opt_in(item)
    if item.get("status") not in ("active", "paused") and not awaiting_catalog:
        result.skipped = f"estado real '{item.get('status')}'"
        return result
    is_paused = item["status"] == "paused"
    sale_terms = with_handling_time(item.get("sale_terms"))
    if sale_terms is not None:
        result.actions.append(f"tiempo de disponibilidad {HANDLING_TIME}")
        if apply:
            ml.update_listing(listing.external_id, sale_terms=sale_terms)
    keys = listing_keys(listing.product_id, item)
    if not is_paused:
        live_keys |= keys

    blocker = reactivation_blocker(item, keys, live_keys) if is_paused else None
    if blocker:
        result.skipped = f"sigue pausado: {blocker}"
        return result

    opportunity, source_product = origin_source(db, listing)
    blocker = buy_source_blocker(opportunity, source_product, utcnow())
    if blocker or opportunity is None:
        result.skipped = f"{'sigue pausado: ' if is_paused else ''}{blocker} — sin cambios"
        return result

    access_token = ml._access_token  # noqa: SLF001
    assert access_token is not None
    buy = Decimal(opportunity.buy_price)
    other = (
        Decimal(opportunity.tax_cost or 0)
        + Decimal(opportunity.payment_cost or 0)
        + Decimal(opportunity.other_cost or 0)
    )
    listing_type = (
        TARGET_LISTING_TYPE if item.get("listing_type_id") == "free" else item["listing_type_id"]
    )
    fallback_ship = Decimal(opportunity.shipping_cost or 0)

    def fee_for(price: Decimal) -> Decimal:
        pct = category_lookup.get_sale_commission_pct(
            item["category_id"],
            price,
            client=ml._client,  # noqa: SLF001
            access_token=access_token,
            listing_type_id=listing_type,
        )
        return price * (pct if pct is not None else settings.marketplace_commission_pct)

    def ship_for(price: Decimal) -> Decimal:
        cost = ml.get_free_shipping_cost(item, price, listing_type)
        return cost if cost is not None else fallback_ship

    floor = minimum_profitable_price(
        buy, other, fee_for, ship_for, settings.min_roi, settings.min_net_profit
    )

    catalog_product_id = item.get("catalog_product_id")
    catalog_product = ml.get_catalog_product(catalog_product_id) if catalog_product_id else None
    same_product = catalog_product is not None and catalog_matches(item, catalog_product)
    known_catalogs = {
        m.catalog_product_id
        for m in db.query(ListingCatalogMatch).filter_by(marketplace_product_id=listing.id)
    }
    if same_product and catalog_product_id and catalog_product_id not in known_catalogs:
        known_catalogs.add(catalog_product_id)
        if apply:
            db.add(
                ListingCatalogMatch(
                    marketplace_product_id=listing.id, catalog_product_id=catalog_product_id
                )
            )
            db.commit()
    competitors = _competitor_prices(ml, known_catalogs)
    if is_paused and known_catalogs and competitors is None:
        result.skipped = "sigue pausado: no se pudo consultar la competencia"
        return result
    current = Decimal(str(item["price"]))
    decision = decide_price(floor, current, competitors, launch_mode=launch_mode)
    can_opt_in = bool(catalog_product_id and same_product) and should_opt_in_catalog(
        item, launch_mode=launch_mode
    )

    if awaiting_catalog:
        blocker = catalog_rescue_blocker(decision, current, floor, can_opt_in=can_opt_in)
        if blocker:
            result.skipped = f"en revisión, espera catálogo: {blocker}"
            return result
        assert catalog_product_id is not None
        result.actions.append(f"inscribir en catálogo {catalog_product_id} a {current:,.0f}")
        if apply:
            _opt_in(db, ml, listing, catalog_product_id, current)
        return result

    if decision.action == "pause":
        if is_paused:
            result.skipped = f"sigue pausado: {decision.reason}"
            return result
        result.actions.append(f"PAUSAR: {decision.reason}")
        result.paused = True
        if apply:
            listing_service.pause_listing(db, ml, listing, reason=decision.reason)
        return result

    assert decision.price is not None
    new_price = decision.price
    fee = fee_for(new_price)
    ship = ship_for(new_price)
    net = net_profit(new_price, buy, fee, ship, other)
    # Belt and braces: never apply anything that doesn't clear the gate.
    if net < required_profit(buy, settings.min_roi, settings.min_net_profit):
        result.skipped = f"no cumple ROI a {new_price:,.0f} (neto {net:,.0f}) — sin cambios"
        return result
    economics = (
        f"compra {buy:,.0f} comisión {fee:,.0f} envío {ship:,.0f} "
        f"→ neto {net:,.0f} (ROI {net / buy:.0%})"
    )

    if item.get("listing_type_id") == "free":
        result.actions.append(f"Clásica + envío gratis [{economics}]")
        if apply:
            ml.change_listing_type(listing.external_id, TARGET_LISTING_TYPE)
            ml.set_free_shipping(listing.external_id)
    elif not (item.get("shipping") or {}).get("free_shipping"):
        result.actions.append(f"envío gratis [{economics}]")
        if apply:
            ml.set_free_shipping(listing.external_id)

    if new_price != current:
        result.actions.append(
            f"precio {current:,.0f} → {new_price:,.0f} ({decision.reason}) [{economics}]"
        )
        if apply:
            listing_service.update_listing_price(db, ml, listing, new_price)

    if is_paused:
        result.actions.append(f"REACTIVAR a {new_price:,.0f} [{economics}]")
        result.reactivated = True
        live_keys |= keys
        if apply:
            listing_service.activate_listing(db, ml, listing)
        # Catalog opt-in waits for a run where it's already active.
        return result

    if can_opt_in:
        assert catalog_product_id is not None
        result.actions.append(f"inscribir en catálogo {catalog_product_id}")
        if apply:
            _opt_in(db, ml, listing, catalog_product_id, new_price)
    return result
