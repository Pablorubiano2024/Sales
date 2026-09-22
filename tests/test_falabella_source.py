"""Tests for the Falabella source adapter (falabella.com.co).

Uses httpx.MockTransport with fixture HTML matching the real
`__NEXT_DATA__` shape verified live 2026-09-22 (search + product detail
pages) — no real network access.
"""

from __future__ import annotations

import json
from decimal import Decimal

import httpx

from backend.app.integrations.falabella_source import FalabellaSourceAdapter

SEARCH_RESULT = {
    "productId": "73568541",
    "displayName": "Televisor | 65 Pulgadas | Hi-QLED 4K | 65QD5SV",
    "brand": "HISENSE",
    "url": "https://www.falabella.com.co/falabella-co/product/73568541/tv-qled-65-hisense-4k-65qd5sv",
    "prices": [
        {"type": "internetPrice", "crossed": False, "price": ["2.149.900"]},
        {"type": "normalPrice", "crossed": True, "price": ["4.099.900"]},
    ],
    "mediaUrls": [
        "https://media.falabella.com.co/falabellaCO/73568541_01/public",
        "https://media.falabella.com.co/falabellaCO/73568541_02/public",
    ],
}


def _html_with_next_data(page_props: dict) -> str:
    payload = {"props": {"pageProps": page_props}}
    return f'<html><body><script id="__NEXT_DATA__">{json.dumps(payload)}</script></body></html>'


def _adapter(handler) -> FalabellaSourceAdapter:
    return FalabellaSourceAdapter(transport=httpx.MockTransport(handler))


def test_search_products_parses_real_response_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/falabella-co/search"
        assert request.url.params["Ntt"] == "television"
        return httpx.Response(200, text=_html_with_next_data({"results": [SEARCH_RESULT]}))

    adapter = _adapter(handler)
    results = adapter.search_products("television")

    assert len(results) == 1
    product = results[0]
    assert product.external_id == "73568541"
    assert product.name == "Televisor | 65 Pulgadas | Hi-QLED 4K | 65QD5SV"
    # "2.149.900" (period thousands separators) -> 2149900, not the crossed
    # "normalPrice" (4.099.900) — internetPrice is the live sale price.
    assert product.price == Decimal("2149900")
    assert product.currency == "COP"
    assert product.url == SEARCH_RESULT["url"]
    # The crossed-out "normalPrice" is real reference/list price data —
    # must be surfaced, not discarded, so discovery can use it instead of
    # a guessed wholesale-arbitrage markup.
    assert product.reference_price == Decimal("4099900")
    assert product.image_urls == (
        "https://media.falabella.com.co/falabellaCO/73568541_01/public",
        "https://media.falabella.com.co/falabellaCO/73568541_02/public",
    )
    assert product.brand == "HISENSE"


def test_search_products_reference_price_is_none_without_a_real_discount() -> None:
    no_discount = {
        **SEARCH_RESULT,
        "prices": [{"type": "internetPrice", "crossed": False, "price": ["2.149.900"]}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_html_with_next_data({"results": [no_discount]}))

    adapter = _adapter(handler)
    assert adapter.search_products("television")[0].reference_price is None


def test_get_product_uses_event_price_when_no_internet_price() -> None:
    """A limited-time promotion reports its live price as "eventPrice", not
    "internetPrice" — confirmed live 2026-09-22 on a real product. Must not
    depend on it happening to be listed first."""
    product_data = {
        "id": "137938699",
        "name": "Licuadora Ninja Sistema Profesional de Cocina Inteligente 1700 W",
        "isOutOfStock": False,
        "currentVariant": "137938700",
        "variants": [
            {
                "id": "137938700",
                "prices": [
                    {"type": "eventPrice", "crossed": False, "price": ["1.199.900"]},
                    {"type": "normalPrice", "crossed": True, "price": ["3.199.900"]},
                ],
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_html_with_next_data({"productData": product_data}))

    adapter = _adapter(handler)
    product = adapter.get_product("137938699")

    assert product is not None
    assert product.price == Decimal("1199900")
    assert product.reference_price == Decimal("3199900")


def test_search_products_returns_empty_list_when_no_next_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>not what we expect</body></html>")

    adapter = _adapter(handler)
    assert adapter.search_products("anything") == []


def test_search_products_returns_empty_list_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    adapter = _adapter(handler)
    assert adapter.search_products("anything") == []


def test_search_products_respects_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_html_with_next_data({"results": [SEARCH_RESULT] * 5}))

    adapter = _adapter(handler)
    assert len(adapter.search_products("television", limit=2)) == 2


def test_get_product_parses_detail_page_and_stock() -> None:
    product_data = {
        "id": "73568541",
        "name": "Televisor Hisense | 65 Pulgadas | Hi-QLED 4K | 65QD5SV",
        "isOutOfStock": False,
        "prices": [{"type": "internetPrice", "crossed": False, "price": ["2.149.900"]}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/falabella-co/product/73568541"
        return httpx.Response(200, text=_html_with_next_data({"productData": product_data}))

    adapter = _adapter(handler)
    product = adapter.get_product("73568541")

    assert product is not None
    assert product.price == Decimal("2149900")
    assert product.stock_available is True


def test_get_product_falls_back_to_current_variant_prices() -> None:
    """Some product pages carry no top-level `prices` — only the active
    variant's do (see module docstring)."""
    product_data = {
        "id": "1",
        "name": "Some Product",
        "isOutOfStock": False,
        "currentVariant": "1",
        "variants": [{"id": "1", "prices": [{"type": "internetPrice", "price": ["50.000"]}]}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_html_with_next_data({"productData": product_data}))

    adapter = _adapter(handler)
    product = adapter.get_product("1")

    assert product is not None
    assert product.price == Decimal("50000")


def test_get_product_falls_back_to_variant_images_when_top_level_is_a_placeholder() -> None:
    """The top-level `medias` is frequently just a "no image" placeholder —
    real photos live on the active variant's own `medias` — confirmed live
    2026-09-22 on a real product."""
    product_data = {
        "id": "137938699",
        "name": "Licuadora Ninja Sistema Profesional de Cocina Inteligente 1700 W",
        "isOutOfStock": False,
        "currentVariant": "137938700",
        "medias": [
            {
                "id": "default_no_image",
                "url": "https://media.falabella.com/FalabellaPEAndCO/NoImage/public",
                "mediaType": "image",
            }
        ],
        "variants": [
            {
                "id": "137938700",
                "prices": [{"type": "internetPrice", "price": ["1.199.900"]}],
                "medias": [
                    {
                        "id": "real-1",
                        "url": "https://media.falabella.com/falabellaCO/137938700_01/public",
                        "mediaType": "image",
                    },
                    {
                        "id": "real-2",
                        "url": "https://media.falabella.com/falabellaCO/137938700_02/public",
                        "mediaType": "image",
                    },
                ],
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_html_with_next_data({"productData": product_data}))

    adapter = _adapter(handler)
    product = adapter.get_product("137938699")

    assert product is not None
    assert product.image_urls == (
        "https://media.falabella.com/falabellaCO/137938700_01/public",
        "https://media.falabella.com/falabellaCO/137938700_02/public",
    )


def test_get_product_extracts_real_brand_and_specifications() -> None:
    """Falabella reports a real brand and a spec table on the detail page —
    using these instead of a "Genérica"/"Genérico" placeholder is a real
    MercadoLibre publication-quality improvement, confirmed live
    2026-09-22 (Samsung Galaxy Watch published as brand "Genérica" hurt
    its quality score)."""
    product_data = {
        "id": "147573614",
        "name": "Reloj Galaxy Watch 8 40mm Silver",
        "isOutOfStock": False,
        "brandName": "SAMSUNG",
        "prices": [{"type": "internetPrice", "price": ["2.199.900"]}],
        "attributes": {
            "specifications": [
                {"id": "6_model", "name": "Modelo", "value": "SM L320NZSALTA"},
                {
                    "id": "2068_compatible_con",
                    "name": "Compatible con",
                    "value": "Android",
                },
                {"id": "no_value", "name": "Algo sin valor", "value": ""},
            ]
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_html_with_next_data({"productData": product_data}))

    adapter = _adapter(handler)
    product = adapter.get_product("147573614")

    assert product is not None
    assert product.brand == "SAMSUNG"
    assert product.specifications == (
        ("Modelo", "SM L320NZSALTA"),
        ("Compatible con", "Android"),
    )


def test_get_product_marks_out_of_stock() -> None:
    product_data = {
        "id": "1",
        "name": "Sold Out Thing",
        "isOutOfStock": True,
        "prices": [{"type": "internetPrice", "price": ["10.000"]}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_html_with_next_data({"productData": product_data}))

    adapter = _adapter(handler)
    product = adapter.get_product("1")

    assert product is not None
    assert product.stock_available is False


def test_get_product_returns_none_on_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    adapter = _adapter(handler)
    assert adapter.get_product("does-not-exist") is None


def test_get_price_and_get_stock_delegate_to_get_product() -> None:
    product_data = {
        "id": "1",
        "name": "Thing",
        "isOutOfStock": False,
        "prices": [{"type": "internetPrice", "price": ["10.000"]}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_html_with_next_data({"productData": product_data}))

    adapter = _adapter(handler)
    assert adapter.get_price("1") == Decimal("10000")
    assert adapter.get_stock("1") is True


def test_get_product_url_does_not_require_network() -> None:
    adapter = _adapter(lambda request: httpx.Response(500))
    assert adapter.get_product_url("42") == "https://www.falabella.com.co/falabella-co/product/42"
