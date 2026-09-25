"""Tests for the Imusa source adapter (imusa.com.co) — a classic VTEX
commerce API, real response shape verified live 2026-09-25 (see module
docstring). Uses httpx.MockTransport — no real network access."""

from __future__ import annotations

from decimal import Decimal

import httpx

from backend.app.integrations.imusa_source import ImusaSourceAdapter

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
