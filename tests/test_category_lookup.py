"""Tests for category_lookup.py using httpx.MockTransport — response
shapes match domain_discovery/categories-attributes verified live
2026-09-22 (see module docstring)."""

from __future__ import annotations

import httpx

from backend.app.services import category_lookup


def _client(handler) -> httpx.Client:
    return httpx.Client(
        base_url=category_lookup.API_BASE_URL, transport=httpx.MockTransport(handler)
    )


def test_predict_category_returns_top_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/sites/MCO/domain_discovery/search"
        assert request.url.params["q"] == "licuadora"
        return httpx.Response(
            200,
            json=[
                {"category_id": "MCO163045", "category_name": "Licuadoras"},
                {"category_id": "MCO412089", "category_name": "Licuadoras Industriales"},
            ],
        )

    with _client(handler) as client:
        assert category_lookup.predict_category("licuadora", client=client) == "MCO163045"


def test_predict_category_returns_none_when_empty() -> None:
    with _client(lambda r: httpx.Response(200, json=[])) as client:
        assert category_lookup.predict_category("xyzzy", client=client) is None


def test_predict_category_returns_none_on_http_error() -> None:
    with _client(lambda r: httpx.Response(500)) as client:
        assert category_lookup.predict_category("licuadora", client=client) is None


def test_required_attribute_ids_filters_to_required_only() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/categories/MCO163045/attributes"
        return httpx.Response(
            200,
            json=[
                {"id": "BRAND", "tags": {"required": True}},
                {"id": "MODEL", "tags": {"required": True}},
                {"id": "COLOR", "tags": {}},
            ],
        )

    with _client(handler) as client:
        assert category_lookup.required_attribute_ids("MCO163045", client=client) == [
            "BRAND",
            "MODEL",
        ]


def test_is_safe_to_autopublish_true_when_only_brand_and_model_required() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"id": "BRAND", "tags": {"required": True}},
                {"id": "MODEL", "tags": {"required": True}},
            ],
        )

    with _client(handler) as client:
        assert category_lookup.is_safe_to_autopublish("MCO163045", client=client) is True


def test_is_safe_to_autopublish_false_when_extra_attribute_required() -> None:
    """Real example: MCO163045-adjacent blender categories require
    POWER_SUPPLY_TYPE too — verified live 2026-09-22 — with no safe
    per-product value to guess."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"id": "BRAND", "tags": {"required": True}},
                {"id": "MODEL", "tags": {"required": True}},
                {"id": "POWER_SUPPLY_TYPE", "tags": {"required": True}},
            ],
        )

    with _client(handler) as client:
        assert category_lookup.is_safe_to_autopublish("MCO412089", client=client) is False
