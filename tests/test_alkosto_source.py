"""Tests for the Alkosto/Ktronix source adapters (alkosto.com,
ktronix.com) — a real SAP Commerce storefront that embeds schema.org
microdata directly in server-rendered HTML, and whose robots.txt
explicitly disallows `/search/`/`?q=`, so discovery goes through the
explicitly-granted sitemap instead (see module docstring). Uses
httpx.MockTransport — no real network access. The HTML fixture below
mirrors the real structure captured live 2026-10-02 against a real
iPad Air product page, trimmed to just the fields this adapter parses."""

from __future__ import annotations

from decimal import Decimal

import httpx

from backend.app.integrations.alkosto_source import AlkostoSourceAdapter, KtronixSourceAdapter

SPEC_TABLE_HTML = """
<div class="new-container__table__classifications___type__item">
  <div class="...item_feature js-comparableAttributes-data memoria_interna"
       data-attribute-code="memoria_interna_de_la_tableta"
       data-attribute-name="Capacidad de Almacenamiento" data-attribute-action="">
    Capacidad de Almacenamiento</div>
  <div class="new-container__table__classifications___type__item_result"> 128 GB&nbsp </div>
</div>
<div class="new-container__table__classifications___type__item">
  <div class="...item_feature js-comparableAttributes-data nucleos"
       data-attribute-code="nucleos_procesador"
       data-attribute-name="Núcleos del Procesador" data-attribute-action="">
    Núcleos del Procesador</div>
  <div class="new-container__table__classifications___type__item_result"> 8&nbsp Nucleos</div>
</div>
<div class="new-container__table__classifications___type__item">
  <div class="...item_feature js-comparableAttributes-data empty_spec"
       data-attribute-code="empty_spec" data-attribute-name="Resolucion Camara Frontal"
       data-attribute-action="">Resolucion Camara Frontal</div>
  <div class="new-container__table__classifications___type__item_result"></div>
</div>
"""


def _product_html(
    *,
    price: str = "4709010.0",
    availability: str = "InStock",
    base_price_html: str = "",
    spec_html: str = "",
) -> str:
    return f"""
    <html><head>
    <meta property="og:image" content="https://www.alkosto.com/medias/195950797978-001.webp"/>
    </head><body>
    {base_price_html}
    <div itemprop="brand" itemscope itemtype="https://schema.org/Brand"
         class="hidden" aria-hidden="true">
      <meta itemprop="name" content="APPLE"/>
    </div>
    <div itemprop="offers" itemscope itemtype="https://schema.org/Offer"
         class="hidden" aria-hidden="true">
      <link itemprop="availability" href="https://schema.org/{availability}"/>
      <meta itemprop="priceCurrency" content="COP"/>
      <meta itemprop="price" content="{price}"/>
      <div itemprop="seller" itemscope itemtype="https://schema.org/Organization"
           class="hidden" aria-hidden="true">
        <meta itemprop="name" content="Alkosto"/>
      </div>
    </div>
    <h1 class="js-main-title" itemprop="name">iPad Air 13&#34; Pulgadas 128GB Chip M4 WiFi Azul</h1>
    {spec_html}
    </body></html>
    """


SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.alkosto.com/ipad-air-13-m4-128gb-wifi-gr/p/195950797978</loc></url>
  <url><loc>https://www.alkosto.com/freidora-aire-imusa-esencial-32l-manual-negra/p/3045380020665</loc></url>
  <url><loc>https://www.alkosto.com/licuadora-kalley-k-b15mav/p/7705946806725</loc></url>
</urlset>
"""


def _adapter(handler) -> AlkostoSourceAdapter:
    return AlkostoSourceAdapter(transport=httpx.MockTransport(handler))


def test_get_product_parses_real_offer_microdata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/x/p/195950797978"
        return httpx.Response(200, html=_product_html())

    with _adapter(handler) as adapter:
        product = adapter.get_product("195950797978")

    assert product is not None
    assert product.external_id == "195950797978"
    assert product.name == 'iPad Air 13" Pulgadas 128GB Chip M4 WiFi Azul'
    assert product.price == Decimal("4709010.0")
    assert product.currency == "COP"
    assert product.stock_available is True
    assert product.brand == "APPLE"
    assert product.image_urls == ("https://www.alkosto.com/medias/195950797978-001.webp",)
    assert product.reference_price is None
    assert product.specifications == ()


def test_get_product_parses_the_real_specifications_table() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=_product_html(spec_html=SPEC_TABLE_HTML))

    with _adapter(handler) as adapter:
        product = adapter.get_product("195950797978")

    assert product is not None
    assert product.specifications == (
        ("Capacidad de Almacenamiento", "128 GB"),
        ("Núcleos del Procesador", "8 Nucleos"),
    )


def test_get_product_detects_a_real_active_discount() -> None:
    base_price_html = '<span class="before-price__basePrice"> $5.999.000</span>'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, html=_product_html(price="4709010.0", base_price_html=base_price_html)
        )

    with _adapter(handler) as adapter:
        product = adapter.get_product("195950797978")

    assert product is not None
    assert product.reference_price == Decimal("5999000")


def test_get_product_ignores_base_price_when_not_a_real_discount() -> None:
    # Same base price as the live price (e.g. the "hidden" span still
    # rendered with no real markdown) — must not be surfaced as a
    # reference_price, same rule as Falabella's.
    base_price_html = '<span class="before-price__basePrice"> $4.709.010</span>'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, html=_product_html(price="4709010.0", base_price_html=base_price_html)
        )

    with _adapter(handler) as adapter:
        assert adapter.get_product("195950797978").reference_price is None  # type: ignore[union-attr]


def test_get_product_treats_outofstock_availability_as_false() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=_product_html(availability="OutOfStock"))

    with _adapter(handler) as adapter:
        assert adapter.get_product("195950797978").stock_available is False  # type: ignore[union-attr]


def test_get_product_returns_none_on_404() -> None:
    with _adapter(lambda r: httpx.Response(404)) as adapter:
        assert adapter.get_product("does-not-exist") is None


def test_get_product_returns_none_without_offers_microdata() -> None:
    with _adapter(
        lambda r: httpx.Response(200, html="<html><body>nothing here</body></html>")
    ) as adapter:
        assert adapter.get_product("195950797978") is None


def test_get_price_and_get_stock_delegate_to_get_product() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=_product_html())

    with _adapter(handler) as adapter:
        assert adapter.get_price("195950797978") == Decimal("4709010.0")
        assert adapter.get_stock("195950797978") is True


def test_get_product_url_returns_the_real_resolved_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=_product_html())

    with _adapter(handler) as adapter:
        url = adapter.get_product_url("195950797978")

    assert url is not None
    assert url.endswith("/x/p/195950797978")


def test_search_products_matches_via_sitemap_token_overlap() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/sitemap-productos.xml":
            return httpx.Response(200, text=SITEMAP_XML)
        return httpx.Response(200, html=_product_html())

    with _adapter(handler) as adapter:
        results = adapter.search_products("freidora de aire", limit=5)

    # Only the Imusa freidora slug contains every (non-stopword) query
    # token — the iPad and licuadora entries must not match.
    assert len(results) == 1
    assert requested_paths[0] == "/sitemap-productos.xml"
    assert "/x/p/3045380020665" in requested_paths


def test_search_products_returns_empty_when_query_is_only_stopwords() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, text=SITEMAP_XML)

    with _adapter(handler) as adapter:
        assert adapter.search_products("de la") == []

    # The sitemap is never fetched when there's nothing real to match on.
    assert calls == []


def test_search_products_returns_empty_when_sitemap_fetch_fails() -> None:
    with _adapter(lambda r: httpx.Response(500)) as adapter:
        assert adapter.search_products("licuadora") == []


def test_search_products_caches_the_catalog_index_across_calls() -> None:
    sitemap_fetches = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sitemap_fetches
        if request.url.path == "/sitemap-productos.xml":
            sitemap_fetches += 1
            return httpx.Response(200, text=SITEMAP_XML)
        return httpx.Response(200, html=_product_html())

    with _adapter(handler) as adapter:
        adapter.search_products("licuadora")
        adapter.search_products("freidora")

    assert sitemap_fetches == 1


def test_ktronix_adapter_defaults_to_the_real_ktronix_base_url() -> None:
    adapter = KtronixSourceAdapter(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert str(adapter._client.base_url) == "https://www.ktronix.com"  # noqa: SLF001
    assert adapter.source_label == "Ktronix"
