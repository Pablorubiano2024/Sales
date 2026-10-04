"""Tests for the Tecnologia Mayorista source adapter
(tecnologiamayorista.com) — a real Colombian wholesale distributor on a
Shopify storefront, confirmed live 2026-10-04 (see module docstring).
Uses httpx.MockTransport — no real network access. Fixture shapes mirror
real /search/suggest.json responses captured live against a real Xiaomi
air fryer and a real Sokany air fryer (both with a confirmed real
"... B2B" cheaper-price sibling listing)."""

from __future__ import annotations

from decimal import Decimal

import httpx

from backend.app.integrations.tecnologiamayorista_source import (
    TecnologiaMayoristaSourceAdapter,
)

_HANDLE_B2B = (
    "freidora-de-aire-xiaomi-air-fryer-6-5l-con-control-desde-app-y-7-"
    "modos-preestablecidos-bhr084cus-b2b"
)
_HANDLE_B2C = _HANDLE_B2B.removesuffix("-b2b")
_TITLE_B2B = (
    "Freidora De Aire Xiaomi Air Fryer 6.5L Con Control Desde App Y 7 Modos "
    "Preestablecidos BHR084CUS B2B"
)
_TITLE_B2C = _TITLE_B2B.removesuffix(" B2B")

XIAOMI_B2B = {
    "id": 10064274424106,
    "handle": _HANDLE_B2B,
    "title": _TITLE_B2B,
    "price": "325000.00",
    "compare_at_price_max": "459900.00",
    "available": True,
    "vendor": "Tecnologia Mayorista",
    "tags": ["B2B", "cocina"],
    "body": (
        "<ul><li>Tipo: Freidora de aire digital</li>"
        "<li>Modelo: Xiaomi Air Fryer 6.5L</li>"
        "<li>Capacidad: 6.5 litros</li></ul>"
    ),
    "featured_image": {"url": "https://cdn.shopify.com/example-xiaomi.webp"},
}

XIAOMI_B2C = {
    **XIAOMI_B2B,
    "id": 10064274424105,
    "handle": _HANDLE_B2C,
    "title": _TITLE_B2C,
    "price": "399900.00",
    "tags": ["B2C", "cocina"],
}


def _adapter(handler) -> TecnologiaMayoristaSourceAdapter:
    return TecnologiaMayoristaSourceAdapter(transport=httpx.MockTransport(handler))


def _suggest_response(products: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"resources": {"results": {"products": products}}})


def test_search_products_parses_real_response_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search/suggest.json"
        assert request.url.params["q"] == "freidora de aire"
        assert request.url.params["resources[type]"] == "product"
        return _suggest_response([XIAOMI_B2B, XIAOMI_B2C])

    with _adapter(handler) as adapter:
        results = adapter.search_products("freidora de aire")

    assert len(results) == 2
    cheap, expensive = results
    assert cheap.external_id == XIAOMI_B2B["handle"]
    assert cheap.price == Decimal("325000.00")
    assert cheap.currency == "COP"
    assert cheap.stock_available is True
    assert cheap.reference_price == Decimal("459900.00")
    assert cheap.brand is None
    assert cheap.specifications == (
        ("Tipo", "Freidora de aire digital"),
        ("Modelo", "Xiaomi Air Fryer 6.5L"),
        ("Capacidad", "6.5 litros"),
    )
    assert cheap.image_urls == ("https://cdn.shopify.com/example-xiaomi.webp",)
    assert expensive.price == Decimal("399900.00")


def test_search_products_filters_implausible_matches() -> None:
    unrelated = {**XIAOMI_B2B, "title": "Totally unrelated replacement cable"}

    def handler(request: httpx.Request) -> httpx.Response:
        return _suggest_response([unrelated])

    with _adapter(handler) as adapter:
        results = adapter.search_products("freidora de aire")
    assert results == []


def test_search_products_reference_price_none_without_a_real_discount() -> None:
    no_discount = {**XIAOMI_B2B, "compare_at_price_max": "325000.00"}

    def handler(request: httpx.Request) -> httpx.Response:
        return _suggest_response([no_discount])

    with _adapter(handler) as adapter:
        assert adapter.search_products("freidora de aire")[0].reference_price is None


def test_search_products_returns_empty_list_on_http_error() -> None:
    with _adapter(lambda r: httpx.Response(500)) as adapter:
        assert adapter.search_products("freidora de aire") == []


def test_search_products_retries_once_on_rate_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.app.integrations.tecnologiamayorista_source.RATE_LIMIT_RETRY_SECONDS", 0.0
    )
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, text="local_rate_limited")
        return _suggest_response([XIAOMI_B2B])

    with _adapter(handler) as adapter:
        results = adapter.search_products("freidora de aire")

    assert calls["n"] == 2
    assert len(results) == 1


def test_get_product_matches_the_exact_handle() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["q"] == _HANDLE_B2B.replace("-", " ")
        return _suggest_response([XIAOMI_B2C, XIAOMI_B2B])

    with _adapter(handler) as adapter:
        product = adapter.get_product(XIAOMI_B2B["handle"])

    assert product is not None
    assert product.external_id == XIAOMI_B2B["handle"]
    assert product.price == Decimal("325000.00")


def test_get_product_returns_none_when_handle_not_in_results() -> None:
    with _adapter(lambda r: _suggest_response([XIAOMI_B2C])) as adapter:
        assert adapter.get_product("does-not-exist-handle") is None


def test_get_price_and_get_stock_delegate_to_get_product() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _suggest_response([XIAOMI_B2B])

    with _adapter(handler) as adapter:
        assert adapter.get_price(XIAOMI_B2B["handle"]) == Decimal("325000.00")
        assert adapter.get_stock(XIAOMI_B2B["handle"]) is True


def test_get_product_url_builds_the_real_product_path() -> None:
    with _adapter(lambda r: httpx.Response(500)) as adapter:
        url = adapter.get_product_url("some-handle")
    assert url == "https://www.tecnologiamayorista.com/products/some-handle"
