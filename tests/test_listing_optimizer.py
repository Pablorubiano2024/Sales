"""Tests for listing_optimizer.py's pure decision logic — the ROI floor,
competitor-based pricing and the same-product guard. Examples come from
real listings checked live 2026-10-09."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.models.marketplace import Marketplace
from backend.app.models.opportunity import Opportunity, OpportunityStatus
from backend.app.models.product import Product
from backend.app.models.source import Source, SourceProduct, SourceType
from backend.app.services.listing_optimizer import (
    PriceDecision,
    _competitor_prices,
    awaits_catalog_opt_in,
    buy_source_blocker,
    catalog_matches,
    catalog_rescue_blocker,
    decide_price,
    decide_publish_price,
    find_market_prices,
    is_origin_opportunity,
    listing_keys,
    minimum_profitable_price,
    reactivation_blocker,
    round_price_down,
    round_price_up,
    should_opt_in_catalog,
)

D = Decimal


def _item(title: str, brand: str, model: str) -> dict:
    return {
        "title": title,
        "attributes": [{"id": "BRAND", "value_name": brand}, {"id": "MODEL", "value_name": model}],
    }


def _catalog(name: str, brand: str, model: str) -> dict:
    return {
        "name": name,
        "attributes": [{"id": "BRAND", "value_name": brand}, {"id": "MODEL", "value_name": model}],
    }


def test_rounding_to_900_prices() -> None:
    assert round_price_up(D("223101")) == D("223900")
    assert round_price_up(D("223900")) == D("223900")
    assert round_price_down(D("782001")) == D("781900")
    assert round_price_down(D("781900")) == D("781900")


def test_floor_clears_roi_with_price_dependent_fee_and_shipping() -> None:
    buy = D("144900")
    floor = minimum_profitable_price(
        buy, D("0"), lambda p: p * D("0.12"), lambda p: D("8000"), D("0.30"), D("20000")
    )
    net = floor - buy - floor * D("0.12") - D("8000")
    assert net >= buy * D("0.30")
    # and it's the lowest such "...900" price
    lower = floor - 1000
    assert lower - buy - lower * D("0.12") - D("8000") < buy * D("0.30")


def test_floor_respects_min_net_profit_on_cheap_items() -> None:
    floor = minimum_profitable_price(
        D("20000"), D("0"), lambda p: D("0"), lambda p: D("0"), D("0.30"), D("20000")
    )
    assert floor - D("20000") >= D("20000")


def test_undercuts_cheapest_competitor_even_if_that_raises_price() -> None:
    decision = decide_price(D("400000"), D("659900"), [D("789900")])
    assert decision.action == "price"
    assert decision.price == D("781900")


def test_pauses_when_floor_cannot_beat_competitor() -> None:
    decision = decide_price(D("223900"), D("249900"), [D("138800"), D("150000")])
    assert decision.action == "pause"


def test_no_competitor_data_keeps_current_price() -> None:
    assert decide_price(D("400000"), D("699900"), None).price == D("699900")
    assert decide_price(D("400000"), D("699900"), []).price == D("699900")


def test_no_competitor_data_raises_to_floor_when_unprofitable() -> None:
    decision = decide_price(D("459900"), D("399900"), None)
    assert decision.price == D("459900")


def test_same_model_matches() -> None:
    assert catalog_matches(
        _item("Freidora Ventana 6 Lt", "Huken", "HU-AF-6WT"),
        _catalog("Freidora De Aire Easy-view 6 L", "Huken", "HU-AF-6WT"),
    )


def test_manufacturer_code_vs_commercial_model_still_matches() -> None:
    assert catalog_matches(
        _item("Reloj Galaxy Watch 8 40mm Silver", "Samsung", "SM L320NZSALTA"),
        _catalog("Samsung Galaxy Watch8 40mm Silver", "Samsung", "Watch 8 40mm"),
    )


def test_lite_variant_is_a_different_product() -> None:
    assert not catalog_matches(
        _item("Xiaomi Redmi Watch 6 Lite Amoled 1.96 Gps", "Xiaomi", "M2565W1"),
        _catalog('Smartband Redmi Watch 6 display de 2.07"', "Redmi", "watch 6"),
    )


def test_different_brand_never_matches() -> None:
    assert not catalog_matches(
        _item("Licuadora 1700 W", "Ninja", "BL770"),
        _catalog("Repuesto cuchilla licuadora 1700 W", "Generica", "X1"),
    )


def test_launch_mode_prices_at_floor_even_with_cheaper_room_above() -> None:
    # Ventana, 2026-10-13: 16% under the only competitor still lost the
    # Buy Box (reputation_below_threshold) -> launch prices at the floor.
    decision = decide_price(D("481900"), D("659900"), [D("789900")], launch_mode=True)
    assert decision.action == "price"
    assert decision.price == D("481900")


def test_launch_mode_prices_at_floor_without_competitors() -> None:
    assert decide_price(D("622900"), D("779900"), None, launch_mode=True).price == D("622900")


def test_launch_mode_still_pauses_when_competitor_below_floor() -> None:
    decision = decide_price(D("1574900"), D("2199900"), [D("999999")], launch_mode=True)
    assert decision.action == "pause"


def test_launch_mode_never_goes_below_floor_when_current_is_lower() -> None:
    assert decide_price(D("459900"), D("399900"), None, launch_mode=True).price == D("459900")


NOW = datetime(2026, 10, 15, 13, 0)
PAUSED_BY_US = {"status": "paused", "sub_status": ["paused_by_seller"], "available_quantity": 1}


def _source(in_stock: bool = True, age_h: int = 1) -> SourceProduct:
    return SourceProduct(stock_available=in_stock, last_checked_at=NOW - timedelta(hours=age_h))


def test_reactivation_only_undoes_our_own_pause_with_ml_stock() -> None:
    # Quick 3.5L, 2026-10-15: paused after a one-off source fetch failure.
    keys = listing_keys("p1", PAUSED_BY_US)
    assert reactivation_blocker(PAUSED_BY_US, keys, set()) is None
    assert reactivation_blocker({**PAUSED_BY_US, "sub_status": ["suspended"]}, keys, set())
    assert reactivation_blocker({**PAUSED_BY_US, "available_quantity": 0}, keys, set())
    sold_out = {**PAUSED_BY_US, "sub_status": ["out_of_stock"], "available_quantity": 0}
    assert reactivation_blocker(sold_out, keys, set()) is None


def test_never_reactivates_a_duplicate() -> None:
    # Imusa Esencial 3.2L, 2026-10-15: two product rows, one catalog product.
    item = {**PAUSED_BY_US, "catalog_product_id": "MCO19641188"}
    live = listing_keys("other-product", {"catalog_product_id": "MCO19641188"})
    assert reactivation_blocker(item, listing_keys("p1", item), live)
    assert reactivation_blocker(PAUSED_BY_US, {"product:p1"}, {"product:p1"})


def test_origin_source_must_be_fresh_in_stock_and_viable() -> None:
    approved = Opportunity(status=OpportunityStatus.APPROVED)
    assert buy_source_blocker(approved, _source(), NOW) is None
    assert buy_source_blocker(None, None, NOW)
    assert buy_source_blocker(approved, _source(in_stock=False), NOW)
    # One-off fetch failure: not re-checked today -> leave it alone.
    assert buy_source_blocker(approved, _source(age_h=72), NOW)
    rejected = Opportunity(status=OpportunityStatus.REJECTED)
    assert buy_source_blocker(rejected, _source(), NOW)


class _FakeML:
    def __init__(self, prices: dict[str, list[Decimal] | None]) -> None:
        self.prices = prices

    def get_catalog_competitor_prices(self, catalog_id: str) -> list[Decimal] | None:
        return self.prices[catalog_id]


def test_competitors_checked_across_every_remembered_catalog() -> None:
    # Xiaomi Watch 5, 2026-10-15: suggested catalog flips between an empty
    # one and the one where 38 sellers start at 132,000.
    ml = _FakeML({"MCO44035967": [], "MCO43319779": [D("132000"), D("140000")]})
    prices = _competitor_prices(ml, {"MCO44035967", "MCO43319779"})  # type: ignore[arg-type]
    assert prices == [D("132000"), D("140000")]


def test_competitors_unknown_when_any_lookup_fails_or_none_known() -> None:
    ml = _FakeML({"A": [D("1")], "B": None})
    assert _competitor_prices(ml, {"A", "B"}) is None  # type: ignore[arg-type]
    assert _competitor_prices(ml, set()) is None  # type: ignore[arg-type]


def test_launch_mode_opts_in_only_forewarned_items():
    eligible = {"tags": ["catalog_listing_eligible"]}
    forewarned = {"tags": ["catalog_listing_eligible", "catalog_forewarning"]}
    assert not should_opt_in_catalog(eligible, launch_mode=True)
    assert should_opt_in_catalog(forewarned, launch_mode=True)
    assert should_opt_in_catalog(eligible, launch_mode=False)
    assert not should_opt_in_catalog(
        {**forewarned, "item_relations": [{"id": "MCO1"}]}, launch_mode=True
    )


def test_forewarned_item_matches_shorter_catalog_name():
    attrs = [{"id": "BRAND", "value_name": "Xiaomi"}, {"id": "MODEL", "value_name": "M2523W1"}]
    item = {"title": "Reloj Xiaomi Redmi Watch 6 Pantalla Amoled De 2.07", "attributes": attrs}
    catalog = {
        "name": "Redmi Watch 6 Blue",
        "attributes": [{"id": "BRAND", "value_name": "Xiaomi"}, {"id": "MODEL", "value_name": "6"}],
    }
    assert not catalog_matches(item, catalog)
    forewarned = {**item, "tags": ["catalog_forewarning"]}
    assert catalog_matches(forewarned, catalog)
    lite = {**forewarned, "title": "Xiaomi Redmi Watch 6 Lite Amoled 1.96"}
    assert not catalog_matches(lite, catalog)


def test_publish_price_needs_real_competitors() -> None:
    for prices in (None, []):
        decision = decide_publish_price(D("400000"), prices, launch_mode=False)
        assert decision.action == "skip"
        assert decision.price is None


def test_publish_price_skips_when_competitor_is_below_the_floor() -> None:
    decision = decide_publish_price(D("790900"), [D("665000")], launch_mode=True)
    assert decision.action == "skip"
    assert "665,000" in decision.reason


def test_publish_price_undercuts_the_cheapest_competitor() -> None:
    decision = decide_publish_price(D("400000"), [D("789900"), D("800000")], launch_mode=False)
    assert decision.price == D("781900")


def test_publish_price_in_launch_mode_is_the_floor() -> None:
    decision = decide_publish_price(D("481900"), [D("789900")], launch_mode=True)
    assert decision.price == D("481900")


class _SearchML:
    def __init__(self, results: dict[str, list[dict]]) -> None:
        self.results = results
        self.queries: list[str] = []
        self.priced: list[str] = []

    def search_catalog_products(self, query: str) -> list[dict]:
        self.queries.append(query)
        return self.results.get(query, [])

    def get_catalog_competitor_prices(self, catalog_id: str) -> list[Decimal]:
        self.priced.append(catalog_id)
        return [D("500000")]


def test_market_prices_ignore_a_different_product_and_use_the_exact_one() -> None:
    wrong = {**_catalog("Repuesto Aspas Licuadora", "Otra", "X1"), "id": "WRONG"}
    right = {**_catalog("Licuadora Ninja", "Ninja", "TB400LA"), "id": "RIGHT"}
    ml = _SearchML({"Ninja TB400LA": [wrong, right]})

    prices = find_market_prices(ml, "Licuadora Ninja Sistema", "Ninja", "TB400LA")  # type: ignore[arg-type]

    assert prices == [D("500000")]
    assert ml.priced == ["RIGHT"]


def test_market_prices_are_unknown_without_a_verified_product() -> None:
    ml = _SearchML({"Licuadora Ninja": [{**_catalog("Otra Cosa", "Otra", "X1"), "id": "X"}]})

    assert find_market_prices(ml, "Licuadora Ninja", "Ninja", "Genérico") is None  # type: ignore[arg-type]
    assert ml.queries == ["Licuadora Ninja"]
    assert ml.priced == []


def test_only_the_rows_origin_source_can_publish(db_session: Session) -> None:
    origin = Source(name="Origin Store", source_type=SourceType.API)
    other = Source(name="Other Store", source_type=SourceType.API)
    marketplace = Marketplace(name="Test Marketplace")
    product = Product(sku="ORI-1", name="Licuadora")
    db_session.add_all([origin, other, marketplace, product])
    db_session.commit()
    opportunities = {}
    for source, external_id in ((origin, "1"), (other, "2")):
        db_session.add(
            SourceProduct(
                source_id=source.id,
                product_id=product.id,
                external_id=external_id,
                current_price=D("100000"),
            )
        )
        opportunities[source.name] = Opportunity(
            product_id=product.id,
            source_id=source.id,
            marketplace_id=marketplace.id,
            buy_price=D("100000"),
            sell_price=D("200000"),
        )
        db_session.add(opportunities[source.name])
    db_session.commit()

    assert is_origin_opportunity(db_session, opportunities["Origin Store"])
    assert not is_origin_opportunity(db_session, opportunities["Other Store"])


def test_only_a_forewarned_item_under_review_awaits_the_catalog() -> None:
    forewarned = ["catalog_forewarning"]
    assert awaits_catalog_opt_in({"status": "under_review", "tags": forewarned})
    assert not awaits_catalog_opt_in({"status": "under_review", "tags": []})
    assert not awaits_catalog_opt_in({"status": "active", "tags": forewarned})


def test_catalog_rescue_needs_a_competitive_profitable_verified_product() -> None:
    price = PriceDecision("price", D("600900"), "")
    pause = PriceDecision("pause", None, "competidor")
    floor = D("600900")
    assert catalog_rescue_blocker(price, floor, floor, can_opt_in=True) is None
    assert catalog_rescue_blocker(pause, floor, floor, can_opt_in=True)
    assert catalog_rescue_blocker(price, floor - 1, floor, can_opt_in=True)
    assert catalog_rescue_blocker(price, floor, floor, can_opt_in=False)
