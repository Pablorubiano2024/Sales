"""Tests for the Imusa/Jumbo source adapters (imusa.com.co,
jumbocolombia.com) — a classic VTEX commerce API, real response shape
verified live 2026-09-25 (see module docstring). Uses httpx.MockTransport
— no real network access."""

from __future__ import annotations

from decimal import Decimal

import httpx

from backend.app.integrations.imusa_source import (
    HacebSourceAdapter,
    ImusaSourceAdapter,
    JumboSourceAdapter,
    SonySourceAdapter,
)

PRODUCT = {
    "productId": "1585",
    "productName": "Batería de Cocina IMUSA Talent 10 Piezas Antiadherente",
    "brand": "IMUSA",
    "link": "https://www.imusa.com.co/bateria-de-cocina-imusa-talent-10-piezas-antiadherente/p",
    "allSpecifications": ["Tipo de producto", "Color", "Material", "ShortList", "Html"],
    "Tipo de producto": ["Baterias de cocina"],
    "Color": ["Negro y Gris"],
    "Material": ["Aluminio Antiadherente", "Aluminio"],
    "ShortList": ["some marketing copy, not a real spec"],
    "Html": ["https://example.com/asset.html"],
    "items": [
        {
            "itemId": "1584",
            "images": [{"imageUrl": "https://imusa.vteximg.com.br/arquivos/foo.jpg"}],
            "sellers": [
                {
                    "commertialOffer": {
                        "Price": 199900.0,
                        "ListPrice": 332900.0,
                        "AvailableQuantity": 99999,
                        "IsAvailable": True,
                    }
                }
            ],
        }
    ],
}


def _adapter(handler) -> ImusaSourceAdapter:
    return ImusaSourceAdapter(transport=httpx.MockTransport(handler))


def test_search_products_parses_real_response_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/catalog_system/pub/products/search/ollas"
        assert request.url.params["_from"] == "0"
        return httpx.Response(206, json=[PRODUCT])

    with _adapter(handler) as adapter:
        results = adapter.search_products("ollas")

    assert len(results) == 1
    product = results[0]
    assert product.external_id == "1585"
    assert product.name == "Batería de Cocina IMUSA Talent 10 Piezas Antiadherente"
    assert product.price == Decimal("199900.0")
    assert product.reference_price == Decimal("332900.0")
    assert product.brand == "IMUSA"
    assert product.stock_available is True
    assert product.image_urls == ("https://imusa.vteximg.com.br/arquivos/foo.jpg",)
    # ShortList/Html are real VTEX fields but not real product
    # characteristics — must be dropped, not surfaced as specs.
    assert product.specifications == (
        ("Tipo de producto", "Baterias de cocina"),
        ("Color", "Negro y Gris"),
        ("Material", "Aluminio Antiadherente, Aluminio"),
    )


def test_search_products_reference_price_none_without_a_real_discount() -> None:
    same_price = {**PRODUCT}
    same_price["items"] = [
        {
            **PRODUCT["items"][0],
            "sellers": [
                {
                    "commertialOffer": {
                        "Price": 199900.0,
                        "ListPrice": 199900.0,
                        "AvailableQuantity": 10,
                        "IsAvailable": True,
                    }
                }
            ],
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(206, json=[same_price])

    with _adapter(handler) as adapter:
        assert adapter.search_products("ollas")[0].reference_price is None


def test_search_products_out_of_stock_when_quantity_is_zero() -> None:
    out_of_stock = {**PRODUCT}
    out_of_stock["items"] = [
        {
            **PRODUCT["items"][0],
            "sellers": [
                {
                    "commertialOffer": {
                        "Price": 199900.0,
                        "ListPrice": None,
                        "AvailableQuantity": 0,
                        "IsAvailable": True,
                    }
                }
            ],
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(206, json=[out_of_stock])

    with _adapter(handler) as adapter:
        assert adapter.search_products("ollas")[0].stock_available is False


def test_search_products_returns_empty_list_on_http_error() -> None:
    with _adapter(lambda r: httpx.Response(500)) as adapter:
        assert adapter.search_products("ollas") == []


def test_search_products_skips_product_with_no_items() -> None:
    no_items = {**PRODUCT, "items": []}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(206, json=[no_items])

    with _adapter(handler) as adapter:
        assert adapter.search_products("ollas") == []


def test_get_product_uses_the_productid_filter_query() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/catalog_system/pub/products/search"
        assert request.url.params["fq"] == "productId:1585"
        return httpx.Response(200, json=[PRODUCT])

    with _adapter(handler) as adapter:
        product = adapter.get_product("1585")

    assert product is not None
    assert product.external_id == "1585"


def test_get_product_returns_none_when_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    with _adapter(handler) as adapter:
        assert adapter.get_product("does-not-exist") is None


def test_get_price_and_get_stock_delegate_to_get_product() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[PRODUCT])

    with _adapter(handler) as adapter:
        assert adapter.get_price("1585") == Decimal("199900.0")
        assert adapter.get_stock("1585") is True


def test_get_product_url_delegates_to_get_product() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[PRODUCT])

    with _adapter(handler) as adapter:
        assert adapter.get_product_url("1585") == PRODUCT["link"]


def test_specifications_drop_serialized_json_blob_values() -> None:
    """Confirmed live on Jumbo 2026-09-25: some fields (ProductData,
    SkuData) are internal metadata whose "value" is a serialized JSON
    blob, not human-readable text — must never be surfaced as a spec,
    regardless of field name."""
    jumbo_like = {
        **PRODUCT,
        "allSpecifications": ["Vendido por", "ProductData", "SkuData"],
        "Vendido por": ["Jumbo"],
        "ProductData": ['{"allow_notes":true,"brandName":"TASTY"}'],
        "SkuData": ['{"331069":{"ref_id":"3640749"}}'],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(206, json=[jumbo_like])

    with _adapter(handler) as adapter:
        product = adapter.search_products("licuadora")[0]

    assert product.specifications == (("Vendido por", "Jumbo"),)


def test_jumbo_adapter_defaults_to_the_real_jumbo_base_url() -> None:
    adapter = JumboSourceAdapter(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert str(adapter._client.base_url) == "https://www.jumbocolombia.com"  # noqa: SLF001
    assert adapter.source_label == "Jumbo"


def _with_item(**changes: object) -> dict:
    item = {**PRODUCT["items"][0], **changes}
    return {**PRODUCT, "items": [item]}


def test_parses_the_item_ean_as_gtin() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_with_item(ean="7704353462319")])

    with _adapter(handler) as adapter:
        assert adapter.search_products("x")[0].gtin == "7704353462319"


def test_eleven_digit_ean_is_a_upc_missing_its_leading_zero() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[_with_item(ean="27242925502")])

    with SonySourceAdapter(transport=httpx.MockTransport(handler)) as adapter:
        product = adapter.search_products("audifonos")[0]
    assert product.gtin == "027242925502"


def test_no_ean_means_no_gtin() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[PRODUCT])

    with _adapter(handler) as adapter:
        assert adapter.search_products("x")[0].gtin is None


def test_brand_stores_point_at_their_own_site() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        return httpx.Response(200, json=[{**PRODUCT, "brand": "Industrias Haceb S.A."}])

    with SonySourceAdapter(transport=httpx.MockTransport(handler)) as sony:
        sony.search_products("x")
    with HacebSourceAdapter(transport=httpx.MockTransport(handler)) as haceb:
        # The store reports its company name; MercadoLibre knows the brand.
        assert haceb.search_products("x")[0].brand == "Haceb"
    assert seen == ["store.sony.com.co", "www.haceb.com"]


def test_vtex_full_size_asks_for_a_1200px_image() -> None:
    from backend.app.integrations.imusa_source import _vtex_full_size

    base = "https://kaidcol.vteximg.com.br/arquivos/ids/"
    assert (
        _vtex_full_size(base + "157150/K45SSOB-Modulo-2.jpg?v=1")
        == base + "157150-1200-1200/K45SSOB-Modulo-2.jpg?v=1"
    )
    assert _vtex_full_size(base + "157150-500-500/x.jpg") == base + "157150-1200-1200/x.jpg"
