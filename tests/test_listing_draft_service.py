"""Tests for listing_draft_service.py (Autopilot Phase 3), using
httpx.MockTransport for the MercadoLibre category/attribute calls — same
pattern as tests/test_category_lookup.py."""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from backend.app.integrations.base import SourceProductInfo
from backend.app.models.listing_draft import ListingDraft, ListingDraftStatus
from backend.app.models.marketplace import Marketplace
from backend.app.models.opportunity import Opportunity, OpportunityStatus
from backend.app.models.product import Product
from backend.app.models.source import Source, SourceType
from backend.app.services import category_lookup
from backend.app.services.listing_draft_service import (
    DraftGenerationError,
    approve_draft,
    extract_model,
    generate_draft,
    reject_draft,
    truncate_title,
)


def _client(handler) -> httpx.Client:
    return httpx.Client(
        base_url=category_lookup.API_BASE_URL, transport=httpx.MockTransport(handler)
    )


def _make_opportunity(db: Session) -> Opportunity:
    product = Product(sku="DRAFT-1", name="Freidora De Aire Holstein 9 Litros Antiadherente XL")
    source = Source(name="Test Source", source_type=SourceType.MOCK)
    marketplace = Marketplace(name="Test Marketplace")
    db.add_all([product, source, marketplace])
    db.commit()
    db.refresh(product)
    db.refresh(source)
    db.refresh(marketplace)

    opportunity = Opportunity(
        product_id=product.id,
        source_id=source.id,
        marketplace_id=marketplace.id,
        buy_price=Decimal("300000"),
        sell_price=Decimal("500000"),
        status=OpportunityStatus.APPROVED,
    )
    db.add(opportunity)
    db.commit()
    db.refresh(opportunity)
    return opportunity


def _live(**overrides: object) -> SourceProductInfo:
    defaults = dict(
        external_id="ext-1",
        name="Freidora De Aire Holstein 9 Litros",
        price=Decimal("300000"),
        currency="COP",
        stock_available=True,
        image_urls=("https://example.com/photo.jpg",),
        brand="Holstein",
        specifications=(("Modelo", "HOL-AF9"), ("Capacidad", "9 Litros")),
    )
    defaults.update(overrides)
    return SourceProductInfo(**defaults)  # type: ignore[arg-type]


def _handler_safe_category(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/sites/MCO/domain_discovery/search":
        return httpx.Response(
            200, json=[{"category_id": "MCO456045", "category_name": "Freidoras"}]
        )
    if request.url.path == "/categories/MCO456045/attributes":
        return httpx.Response(
            200,
            json=[
                {"id": "BRAND", "tags": {"required": True}},
                {"id": "MODEL", "tags": {"required": True}},
                {
                    "id": "CAPACITY",
                    "name": "Capacidad",
                    "value_type": "string",
                    "tags": {},
                },
            ],
        )
    raise AssertionError(f"unexpected request: {request.url}")


def test_truncate_title_leaves_short_names_untouched() -> None:
    assert truncate_title("Freidora") == "Freidora"


def test_truncate_title_truncates_long_names() -> None:
    name = "x" * 100
    result = truncate_title(name)
    assert len(result) == 60
    assert result.endswith("…")


def test_extract_model_reads_modelo_spec() -> None:
    assert extract_model((("Modelo", "HOL-AF9"), ("Color", "Negro"))) == "HOL-AF9"


def test_extract_model_returns_none_without_modelo_spec() -> None:
    assert extract_model((("Color", "Negro"),)) is None


def test_generate_draft_builds_real_data_only(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    live = _live()

    with _client(_handler_safe_category) as ml_public_client:
        result = generate_draft(db_session, opportunity, live, ml_public_client=ml_public_client)

    assert isinstance(result, ListingDraft)
    assert result.status == ListingDraftStatus.DRAFT
    assert result.category_id == "MCO456045"
    assert result.title == truncate_title(live.name)
    assert result.price == opportunity.sell_price
    assert "HOL-AF9" in (result.description or "")
    assert result.image_urls is not None and "example.com" in result.image_urls


def test_generate_draft_syncs_product_name_from_live_detail_page(db_session: Session) -> None:
    """Real case: Falabella's search-result name can omit a brand word
    ("Imusa") that the detail page includes — the detail page (`live`,
    already fetched by the caller) is the richer, more current one and
    should be synced back onto Product.name for every future caller, not
    just this draft (moved here from publish_approved_opportunities.py
    so both the draft and the real publish see the same synced name)."""
    opportunity = _make_opportunity(db_session)
    live = _live(name="Freidora De Aire Imusa Holstein 9 Litros Antiadherente")

    with _client(_handler_safe_category) as ml_public_client:
        generate_draft(db_session, opportunity, live, ml_public_client=ml_public_client)

    db_session.refresh(opportunity.product)
    assert opportunity.product.name == "Freidora De Aire Imusa Holstein 9 Litros Antiadherente"


def test_generate_draft_returns_error_when_category_not_predicted(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    live = _live()

    with _client(lambda r: httpx.Response(200, json=[])) as ml_public_client:
        result = generate_draft(db_session, opportunity, live, ml_public_client=ml_public_client)

    assert isinstance(result, DraftGenerationError)


def test_generate_draft_returns_error_when_category_needs_unsafe_attributes(
    db_session: Session,
) -> None:
    opportunity = _make_opportunity(db_session)
    live = _live()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sites/MCO/domain_discovery/search":
            return httpx.Response(200, json=[{"category_id": "MCO1", "category_name": "X"}])
        if request.url.path == "/categories/MCO1/attributes":
            return httpx.Response(
                200,
                json=[
                    {"id": "BRAND", "tags": {"required": True}},
                    {"id": "POWER_SUPPLY_TYPE", "tags": {"required": True}},
                ],
            )
        raise AssertionError(f"unexpected request: {request.url}")

    with _client(handler) as ml_public_client:
        result = generate_draft(db_session, opportunity, live, ml_public_client=ml_public_client)

    assert isinstance(result, DraftGenerationError)


def test_generate_draft_allows_a_required_attribute_covered_by_real_specs(
    db_session: Session,
) -> None:
    """2026-10-03 fix: before this, ANY required attribute beyond BRAND/
    MODEL blocked the whole category — even when the product's own real
    specifications already had a confident match for it. A live dry run
    against production showed this was blocking 73 of 74 real "approved"
    opportunities (TVs, neveras, lavadoras...). CAPACITY here is required
    (unlike _handler_safe_category's version, where it's optional) and
    must still succeed because `live`'s real "Capacidad" spec matches it."""
    opportunity = _make_opportunity(db_session)
    live = _live()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sites/MCO/domain_discovery/search":
            return httpx.Response(
                200, json=[{"category_id": "MCO456045", "category_name": "Freidoras"}]
            )
        if request.url.path == "/categories/MCO456045/attributes":
            return httpx.Response(
                200,
                json=[
                    {"id": "BRAND", "tags": {"required": True}},
                    {"id": "MODEL", "tags": {"required": True}},
                    {
                        "id": "CAPACITY",
                        "name": "Capacidad",
                        "value_type": "string",
                        "tags": {"required": True},
                    },
                ],
            )
        raise AssertionError(f"unexpected request: {request.url}")

    with _client(handler) as ml_public_client:
        result = generate_draft(db_session, opportunity, live, ml_public_client=ml_public_client)

    assert isinstance(result, ListingDraft)


def test_generate_draft_still_blocks_a_real_gtin_requirement(db_session: Session) -> None:
    """A real --confirm publish attempt against category MCO11860
    (2026-10-03) proved supplying EMPTY_GTIN_REASON does NOT satisfy a
    real GTIN requirement — MercadoLibre rejected it with
    item.attribute.missing_conditional_required, citing GTIN specifically.
    generate_draft now asks MercadoLibre's own real per-item
    `/attributes/conditional` check (brand="Holstein", the real live()
    fixture's brand) — this test's mock says GTIN is still required for
    that brand, so the category must still be blocked."""
    opportunity = _make_opportunity(db_session)
    live = _live()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sites/MCO/domain_discovery/search":
            return httpx.Response(
                200, json=[{"category_id": "MCO14903", "category_name": "Televisores"}]
            )
        if request.url.path == "/categories/MCO14903/attributes":
            return httpx.Response(
                200,
                json=[
                    {"id": "BRAND", "tags": {"required": True}},
                    {"id": "MODEL", "tags": {"required": True}},
                    {
                        "id": "GTIN",
                        "name": "Código universal de producto",
                        "value_type": "string",
                        # Real shape (confirmed live 2026-10-03) — "multivalued"
                        # is what keeps match_specifications from ever treating
                        # this as a normal matchable attribute.
                        "tags": {"multivalued": True, "conditional_required": True},
                    },
                ],
            )
        if request.url.path == "/categories/MCO14903/attributes/conditional":
            assert request.method == "POST"
            return httpx.Response(200, json={"required_attributes": [{"id": "GTIN"}]})
        raise AssertionError(f"unexpected request: {request.url}")

    with _client(handler) as ml_public_client:
        result = generate_draft(db_session, opportunity, live, ml_public_client=ml_public_client)

    assert isinstance(result, DraftGenerationError)


def test_generate_draft_allows_a_category_when_gtin_not_really_required_for_this_brand(
    db_session: Session,
) -> None:
    """Confirmed live 2026-10-03: GTIN's real per-item requirement is
    brand+category-specific — e.g. required for Electrolux freidoras but
    NOT for KALLEY/IMUSA/generic-brand ones, same category. This test's
    mock says GTIN isn't required for this product's real brand
    ("Holstein", from the `_live()` fixture), so the category must go
    through even though GTIN is conditional_required on the category."""
    opportunity = _make_opportunity(db_session)
    live = _live()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sites/MCO/domain_discovery/search":
            return httpx.Response(
                200, json=[{"category_id": "MCO456045", "category_name": "Freidoras"}]
            )
        if request.url.path == "/categories/MCO456045/attributes":
            return httpx.Response(
                200,
                json=[
                    {"id": "BRAND", "tags": {"required": True}},
                    {"id": "MODEL", "tags": {"required": True}},
                    {
                        "id": "GTIN",
                        "name": "Código universal de producto",
                        "value_type": "string",
                        "tags": {"multivalued": True, "conditional_required": True},
                    },
                ],
            )
        if request.url.path == "/categories/MCO456045/attributes/conditional":
            assert request.method == "POST"
            body = json.loads(request.content)
            assert {"id": "BRAND", "value_name": "Holstein"} in body["attributes"]
            return httpx.Response(200, json={"required_attributes": []})
        raise AssertionError(f"unexpected request: {request.url}")

    with _client(handler) as ml_public_client:
        result = generate_draft(db_session, opportunity, live, ml_public_client=ml_public_client)

    assert isinstance(result, ListingDraft)


def test_generate_draft_covers_gtin_with_a_real_catalog_value(db_session: Session) -> None:
    """2026-10-03: when GTIN really is required (e.g. LG on parlantes)
    and MercadoLibre's own catalog already has a real GTIN on file for
    this exact product, generate_draft must use it — never invent one,
    but also never give up when a real value genuinely exists."""
    opportunity = _make_opportunity(db_session)
    live = _live(name="Parlante LG XBOOM Go", brand="LG")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sites/MCO/domain_discovery/search":
            return httpx.Response(
                200, json=[{"category_id": "MCO11860", "category_name": "Parlantes"}]
            )
        if request.url.path == "/categories/MCO11860/attributes":
            return httpx.Response(
                200,
                json=[
                    {"id": "BRAND", "tags": {"required": True}},
                    {"id": "MODEL", "tags": {"required": True}},
                    {"id": "GTIN", "tags": {"multivalued": True, "conditional_required": True}},
                ],
            )
        if request.url.path == "/categories/MCO11860/attributes/conditional":
            return httpx.Response(200, json={"required_attributes": [{"id": "GTIN"}]})
        if request.url.path == "/products/search":
            assert request.headers["Authorization"] == "Bearer tok123"
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "catalog_product_id": "MCO45056356",
                            "name": "Parlante LG XBOOM Go XBOOM",
                            "attributes": [
                                {
                                    "id": "GTIN",
                                    "values": [{"id": "15996658", "name": "8806098242597"}],
                                }
                            ],
                        }
                    ]
                },
            )
        if request.url.path == "/sites/MCO/listing_prices":
            return httpx.Response(
                200, json=[{"listing_type_id": "gold_special", "sale_fee_amount": 0}]
            )
        raise AssertionError(f"unexpected request: {request.url}")

    with _client(handler) as ml_public_client:
        result = generate_draft(
            db_session,
            opportunity,
            live,
            ml_public_client=ml_public_client,
            access_token="tok123",
        )

    assert isinstance(result, ListingDraft)
    extra = json.loads(result.attributes or "{}")["extra"]
    assert {"id": "GTIN", "value_name": "8806098242597"} in extra


def test_generate_draft_still_blocks_gtin_when_catalog_has_no_real_value(
    db_session: Session,
) -> None:
    """Same as above but MercadoLibre's catalog has no real GTIN for
    this product either — must stay blocked, never guess one."""
    opportunity = _make_opportunity(db_session)
    live = _live(name="Parlante LG XBOOM Go", brand="LG")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sites/MCO/domain_discovery/search":
            return httpx.Response(
                200, json=[{"category_id": "MCO11860", "category_name": "Parlantes"}]
            )
        if request.url.path == "/categories/MCO11860/attributes":
            return httpx.Response(
                200,
                json=[
                    {"id": "BRAND", "tags": {"required": True}},
                    {"id": "MODEL", "tags": {"required": True}},
                    {"id": "GTIN", "tags": {"multivalued": True, "conditional_required": True}},
                ],
            )
        if request.url.path == "/categories/MCO11860/attributes/conditional":
            return httpx.Response(200, json={"required_attributes": [{"id": "GTIN"}]})
        if request.url.path == "/products/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "catalog_product_id": "MCO45056356",
                            "name": "Parlante LG XBOOM Go XBOOM",
                            "attributes": [],
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    with _client(handler) as ml_public_client:
        result = generate_draft(
            db_session,
            opportunity,
            live,
            ml_public_client=ml_public_client,
            access_token="tok123",
        )

    assert isinstance(result, DraftGenerationError)


def test_generate_draft_is_idempotent_per_opportunity(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    live = _live()

    with _client(_handler_safe_category) as ml_public_client:
        first = generate_draft(db_session, opportunity, live, ml_public_client=ml_public_client)
        second = generate_draft(db_session, opportunity, live, ml_public_client=ml_public_client)

    assert isinstance(first, ListingDraft) and isinstance(second, ListingDraft)
    assert first.id == second.id
    assert db_session.query(ListingDraft).filter_by(opportunity_id=opportunity.id).count() == 1


def test_approve_draft_moves_to_ready(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    live = _live()
    with _client(_handler_safe_category) as ml_public_client:
        draft = generate_draft(db_session, opportunity, live, ml_public_client=ml_public_client)
    assert isinstance(draft, ListingDraft)

    approved = approve_draft(db_session, draft)
    assert approved.status == ListingDraftStatus.READY


def test_reject_draft_records_reason(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    live = _live()
    with _client(_handler_safe_category) as ml_public_client:
        draft = generate_draft(db_session, opportunity, live, ml_public_client=ml_public_client)
    assert isinstance(draft, ListingDraft)

    rejected = reject_draft(db_session, draft, "precio ya no es competitivo")
    assert rejected.status == ListingDraftStatus.REJECTED
    assert rejected.rejection_reason == "precio ya no es competitivo"


def test_generate_draft_regenerating_a_rejected_draft_resets_status(db_session: Session) -> None:
    opportunity = _make_opportunity(db_session)
    live = _live()
    with _client(_handler_safe_category) as ml_public_client:
        draft = generate_draft(db_session, opportunity, live, ml_public_client=ml_public_client)
        assert isinstance(draft, ListingDraft)
        reject_draft(db_session, draft, "stock agotado")

        regenerated = generate_draft(
            db_session, opportunity, live, ml_public_client=ml_public_client
        )

    assert isinstance(regenerated, ListingDraft)
    assert regenerated.status == ListingDraftStatus.DRAFT
    assert regenerated.rejection_reason is None
