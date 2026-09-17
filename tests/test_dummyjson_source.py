"""Tests for the DummyJSON HTTP source adapter.

Uses httpx.MockTransport so these tests exercise real request/response
parsing and error handling without any actual network access.
"""

from __future__ import annotations

from decimal import Decimal

import httpx

from backend.app.integrations.dummyjson_source import DummyJsonSourceAdapter

SAMPLE_PRODUCT = {
    "id": 101,
    "title": "Apple AirPods Max Silver",
    "price": 549.99,
    "stock": 59,
    "sku": "MOB-APP-APP-101",
    "availabilityStatus": "In Stock",
    "category": "mobile-accessories",
    "brand": "Apple",
    "images": ["https://cdn.dummyjson.com/product-images/mobile-accessories/1.webp"],
}

OUT_OF_STOCK_PRODUCT = {
    "id": 202,
    "title": "Discontinued Widget",
    "price": 10.0,
    "stock": 0,
    "availabilityStatus": "Out of Stock",
}


def _adapter(handler) -> DummyJsonSourceAdapter:
    return DummyJsonSourceAdapter(transport=httpx.MockTransport(handler))


def test_search_products_parses_real_response_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/products/search"
        assert request.url.params["q"] == "phone"
        return httpx.Response(200, json={"products": [SAMPLE_PRODUCT]})

    adapter = _adapter(handler)
    results = adapter.search_products("phone")

    assert len(results) == 1
    product = results[0]
    assert product.external_id == "101"
    assert product.name == "Apple AirPods Max Silver"
    assert product.price == Decimal("549.99")
    assert product.currency == "USD"
    assert product.stock_available is True
    assert product.url == "https://dummyjson.com/products/101"


def test_search_products_marks_out_of_stock_correctly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"products": [OUT_OF_STOCK_PRODUCT]})

    adapter = _adapter(handler)
    results = adapter.search_products("widget")

    assert results[0].stock_available is False


def test_search_products_returns_empty_list_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    adapter = _adapter(handler)
    assert adapter.search_products("anything") == []


def test_search_products_returns_empty_list_on_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    adapter = _adapter(handler)
    assert adapter.search_products("anything") == []


def test_get_product_returns_none_on_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    adapter = _adapter(handler)
    assert adapter.get_product("does-not-exist") is None


def test_get_price_and_get_stock_delegate_to_get_product() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE_PRODUCT)

    adapter = _adapter(handler)
    assert adapter.get_price("101") == Decimal("549.99")
    assert adapter.get_stock("101") is True


def test_get_stock_false_when_product_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    adapter = _adapter(handler)
    assert adapter.get_stock("missing") is False


def test_get_product_url_does_not_require_network() -> None:
    adapter = _adapter(lambda request: httpx.Response(500))
    assert adapter.get_product_url("42") == "https://dummyjson.com/products/42"
