"""Tests for the CJdropshipping adapter, using httpx.MockTransport so no
real network calls happen. Response shapes match CJ's documented API and
the live-tested error messages recorded in cjdropshipping.py's docstring.
"""

from __future__ import annotations

import json
from decimal import Decimal

import httpx

from backend.app.integrations.cjdropshipping import CJDropshippingAdapter

LOGIN_OK = {
    "code": 200,
    "result": True,
    "message": "success",
    "data": {"accessToken": "fake-token-123", "accessTokenExpiryDate": "2027-01-01"},
}

LIST_RESPONSE = {
    "code": 200,
    "result": True,
    "data": {
        "content": [
            {
                "productList": [
                    {
                        "id": "pid-1",
                        "nameEn": "Wireless Earbuds",
                        "sellPrice": "12.50",
                        "sku": "SKU-1",
                        "bigImage": "https://example.com/img.jpg",
                        "warehouseInventoryNum": 42,
                    }
                ]
            }
        ],
        "totalRecords": 1,
    },
}

DETAIL_RESPONSE = {
    "code": 200,
    "result": True,
    "data": {
        "pid": "pid-1",
        "productNameEn": "Wireless Earbuds",
        "sellPrice": "12.50",
        "productSku": "SKU-1",
        "bigImage": "https://example.com/img.jpg",
        "variants": [
            {
                "vid": "v1",
                "variantSku": "SKU-1-A",
                "variantSellPrice": "12.50",
                "inventories": [{"countryCode": "US", "totalInventory": 42}],
            }
        ],
    },
}


def _adapter(handler) -> CJDropshippingAdapter:
    return CJDropshippingAdapter(
        api_key="CJUserNum@api@fake-key",
        transport=httpx.MockTransport(handler),
    )


def test_search_products_logs_in_then_lists() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("getAccessToken"):
            return httpx.Response(200, json=LOGIN_OK)
        assert request.headers["CJ-Access-Token"] == "fake-token-123"
        return httpx.Response(200, json=LIST_RESPONSE)

    adapter = _adapter(handler)
    results = adapter.search_products("earbuds")

    assert len(results) == 1
    assert results[0].external_id == "pid-1"
    assert results[0].price == Decimal("12.50")
    assert results[0].stock_available is True
    assert any("getAccessToken" in c for c in calls)


def test_login_sends_only_api_key() -> None:
    seen_bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("getAccessToken"):
            seen_bodies.append(json.loads(request.content))
            return httpx.Response(200, json=LOGIN_OK)
        return httpx.Response(200, json=LIST_RESPONSE)

    adapter = _adapter(handler)
    adapter.search_products("earbuds")

    assert seen_bodies == [{"apiKey": "CJUserNum@api@fake-key"}]


def test_not_configured_returns_empty_without_network_call() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=LOGIN_OK)

    adapter = CJDropshippingAdapter(api_key=None, transport=httpx.MockTransport(handler))
    assert adapter.search_products("anything") == []
    assert called is False


def test_login_rejected_returns_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 1600005,
                "result": False,
                "message": "APIkey is wrong, please check and try again",
            },
        )

    adapter = _adapter(handler)
    assert adapter.search_products("anything") == []


def test_get_product_parses_detail_and_total_inventory() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("getAccessToken"):
            return httpx.Response(200, json=LOGIN_OK)
        return httpx.Response(200, json=DETAIL_RESPONSE)

    adapter = _adapter(handler)
    product = adapter.get_product("pid-1")

    assert product is not None
    assert product.price == Decimal("12.50")
    assert product.stock_available is True
    assert adapter.get_price("pid-1") == Decimal("12.50")
    assert adapter.get_stock("pid-1") is True


def test_expired_token_triggers_relogin_once() -> None:
    login_calls = 0
    list_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal login_calls, list_calls
        if request.url.path.endswith("getAccessToken"):
            login_calls += 1
            return httpx.Response(200, json=LOGIN_OK)
        list_calls += 1
        if list_calls == 1:
            return httpx.Response(
                200, json={"code": 1600002, "result": False, "message": "token expired"}
            )
        return httpx.Response(200, json=LIST_RESPONSE)

    adapter = _adapter(handler)
    results = adapter.search_products("earbuds")

    assert len(results) == 1
    assert login_calls == 2
    assert list_calls == 2


def test_get_product_url_returns_none() -> None:
    adapter = _adapter(lambda request: httpx.Response(500))
    assert adapter.get_product_url("pid-1") is None
