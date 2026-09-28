"""Tests for catalog_lookup.py using httpx.MockTransport — response
shapes match GET /products/search and GET /products/{id}/items verified
live 2026-09-28 (see module docstring)."""

from __future__ import annotations

from decimal import Decimal

import httpx

from backend.app.services import catalog_lookup


def _client(handler) -> httpx.Client:
    return httpx.Client(
        base_url=catalog_lookup.API_BASE_URL, transport=httpx.MockTransport(handler)
    )


def test_find_catalog_product_returns_top_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/products/search"
        assert request.url.params["site_id"] == "MCO"
        assert request.url.params["q"] == "iphone 15"
        assert request.headers["Authorization"] == "Bearer tok123"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "catalog_product_id": "MCO27172667",
                        "name": "Apple iPhone 15 (128 GB) - Azul",
                    },
                    {
                        "catalog_product_id": "MCO27172668",
                        "name": "Apple iPhone 15 (128 GB) - Amarillo",
                    },
                ]
            },
        )

    with _client(handler) as client:
        result = catalog_lookup.find_catalog_product(
            "iphone 15", client=client, access_token="tok123"
        )
    assert result == "MCO27172667"


def test_find_catalog_product_returns_none_when_empty() -> None:
    with _client(lambda r: httpx.Response(200, json={"results": []})) as client:
        result = catalog_lookup.find_catalog_product("xyzzy", client=client, access_token="t")
    assert result is None


def test_find_catalog_product_returns_none_on_http_error() -> None:
    with _client(lambda r: httpx.Response(403, json={"message": "forbidden"})) as client:
        result = catalog_lookup.find_catalog_product("iphone 15", client=client, access_token="t")
    assert result is None


def test_find_catalog_product_rejects_a_real_wrong_accessory_match() -> None:
    """Real bug found live 2026-09-28: this exact query top-matched a
    replacement-blade accessory (MCO54625550), not the blender itself —
    which would have fed a $129,900 accessory price into an opportunity
    actually priced at $1,199,900. Locks in the fix."""
    query = "Licuadora Ninja Sistema Profesional de Cocina Inteligente 1700 W Auto."
    candidate_name = (
        "Ninja 6 Navajas 72oz Aspa Cuchilla Licuadora Aspas Para Licuadora Ninja "
        "Repuestos Licuadora Ninja Repuestos Licuadora Ninja"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": [{"catalog_product_id": "MCO54625550", "name": candidate_name}]},
        )

    with _client(handler) as client:
        result = catalog_lookup.find_catalog_product(query, client=client, access_token="t")
    assert result is None


def test_find_catalog_product_rejects_a_real_borderline_wrong_match() -> None:
    """Real case found live 2026-09-28: matched a watch *display* part,
    not the watch itself — 3/6 word overlap, below the 0.6 threshold."""
    query = "Galaxy Watch Ultra 2 Negro + Banda"
    candidate_name = 'Samsung Galaxy Watch Galaxy Watch Ultra display de 1.5"'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": [{"catalog_product_id": "MCO44154070", "name": candidate_name}]},
        )

    with _client(handler) as client:
        result = catalog_lookup.find_catalog_product(query, client=client, access_token="t")
    assert result is None


def test_find_catalog_product_accepts_a_plausible_match() -> None:
    query = "Licuadora Ninja Sistema Profesional de Cocina Inteligente 1700 W Auto."
    candidate_name = "Ninja Sistema Profesional de Cocina Inteligente Licuadora 1700W Automática"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": [{"catalog_product_id": "MCO99999999", "name": candidate_name}]},
        )

    with _client(handler) as client:
        result = catalog_lookup.find_catalog_product(query, client=client, access_token="t")
    assert result == "MCO99999999"


def test_get_buy_box_snapshot_reads_first_result_as_winner() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/products/MCO27172667/items"
        return httpx.Response(
            200,
            json={
                "paging": {"total": 14, "offset": 0, "limit": 100},
                "results": [
                    {"item_id": "MCO4236485256", "seller_id": 1879808182, "price": 2528900},
                    {"item_id": "MCO1982910770", "seller_id": 606851103, "price": 2529900},
                ],
            },
        )

    with _client(handler) as client:
        snapshot = catalog_lookup.get_buy_box_snapshot(
            "MCO27172667", client=client, access_token="tok"
        )
    assert snapshot is not None
    assert snapshot.seller_count == 14
    assert snapshot.buy_box_price == Decimal("2528900")
    assert snapshot.buy_box_seller_id == "1879808182"
    assert snapshot.stock_available is True


def test_get_buy_box_snapshot_handles_no_winners_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404, json={"message": "No winners found", "error": "not_found", "status": 404}
        )

    with _client(handler) as client:
        snapshot = catalog_lookup.get_buy_box_snapshot(
            "MCO27172709", client=client, access_token="tok"
        )
    assert snapshot is not None
    assert snapshot.seller_count == 0
    assert snapshot.buy_box_price is None
    assert snapshot.buy_box_seller_id is None
    assert snapshot.stock_available is False


def test_get_buy_box_snapshot_returns_none_on_unexpected_error() -> None:
    with _client(lambda r: httpx.Response(500)) as client:
        snapshot = catalog_lookup.get_buy_box_snapshot("MCO1", client=client, access_token="tok")
    assert snapshot is None


def test_get_buy_box_snapshot_retries_once_on_rate_limit(monkeypatch) -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, json={"message": "local_rate_limited"})
        return httpx.Response(
            200,
            json={
                "paging": {"total": 1, "offset": 0, "limit": 100},
                "results": [{"item_id": "X", "seller_id": 1, "price": 100}],
            },
        )

    monkeypatch.setattr(catalog_lookup.time, "sleep", lambda _seconds: None)
    with _client(handler) as client:
        snapshot = catalog_lookup.get_buy_box_snapshot("MCO1", client=client, access_token="tok")
    assert calls["count"] == 2
    assert snapshot is not None
    assert snapshot.seller_count == 1
