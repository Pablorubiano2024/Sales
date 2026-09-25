"""Tests for HomecenterSourceAdapter — shares all parsing logic with
FalabellaSourceAdapter (see test_falabella_source.py for the full shape
coverage), so this only covers what's actually different: the real
base_url/path_prefix defaults and the search-redirect behavior confirmed
live 2026-09-25 (homecenter.falabella.com.co/search 301s to a category
page for a recognized term, unlike falabella.com.co's search)."""

from __future__ import annotations

import json

import httpx

from backend.app.integrations.falabella_source import HomecenterSourceAdapter

SEARCH_RESULT = {
    "productId": "118638400",
    "displayName": "Kit Taladro Percutor 1/2 pulgada 20V Max Brushless",
    "brand": "DEWALT",
    "url": "https://homecenter.falabella.com.co/homecenter-co/product/118638400/kit-taladro",
    "prices": [{"type": "internetPrice", "crossed": False, "price": ["384.900"]}],
    "mediaUrls": ["https://media.falabella.com/sodimacCO/554217_1/public"],
}


def _html_with_next_data(page_props: dict) -> str:
    payload = {"props": {"pageProps": page_props}}
    return f'<html><body><script id="__NEXT_DATA__">{json.dumps(payload)}</script></body></html>'


def test_defaults_to_the_real_homecenter_base_url_and_path_prefix() -> None:
    adapter = HomecenterSourceAdapter(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert str(adapter._client.base_url) == "https://homecenter.falabella.com.co"  # noqa: SLF001
    assert adapter._path_prefix == "homecenter-co"  # noqa: SLF001
    assert (
        adapter.get_product_url("118638400")
        == "https://homecenter.falabella.com.co/homecenter-co/product/118638400"
    )


def test_search_follows_the_real_redirect_to_a_category_page() -> None:
    """Confirmed live 2026-09-25: /homecenter-co/search?Ntt=<recognized term>
    301s to a real category page carrying the same results shape — unlike
    falabella.com.co's /search, which returns results directly."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/homecenter-co/search":
            return httpx.Response(
                301,
                headers={"Location": "/homecenter-co/category/CATG32701/Taladros"},
            )
        assert request.url.path == "/homecenter-co/category/CATG32701/Taladros"
        return httpx.Response(200, text=_html_with_next_data({"results": [SEARCH_RESULT]}))

    adapter = HomecenterSourceAdapter(transport=httpx.MockTransport(handler))
    results = adapter.search_products("taladro")

    assert calls == ["/homecenter-co/search", "/homecenter-co/category/CATG32701/Taladros"]
    assert len(results) == 1
    assert results[0].brand == "DEWALT"
