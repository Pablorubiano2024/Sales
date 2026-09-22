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


_MCO118449_ATTRIBUTES = [
    {"id": "BRAND", "name": "Marca", "value_type": "string", "tags": {"required": True}},
    {"id": "MODEL", "name": "Modelo", "value_type": "string", "tags": {"required": True}},
    {
        "id": "DISPLAY_SIZE",
        "name": "Tamaño de la pantalla",
        "value_type": "number_unit",
        "tags": {},
    },
    {"id": "DISPLAY_TYPE", "name": "Tipo de pantalla", "value_type": "string", "tags": {}},
    {
        "id": "SELLER_SKU",
        "name": "SKU",
        "value_type": "string",
        "tags": {"hidden": True, "variation_attribute": True},
    },
]


def test_match_specifications_matches_by_exact_normalized_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_MCO118449_ATTRIBUTES)

    specifications = (("Tipo de pantalla", "Amoled"), ("Modelo", "SM L320NZSALTA"))
    with _client(handler) as client:
        matched = category_lookup.match_specifications("MCO118449", specifications, client=client)

    # "Tipo de pantalla" -> DISPLAY_TYPE (string, safe). "Modelo" is
    # excluded even though it matches — create_listing's own `model` param
    # already handles it.
    assert matched == [{"id": "DISPLAY_TYPE", "value_name": "Amoled"}]


def test_match_specifications_skips_non_string_value_types() -> None:
    """DISPLAY_SIZE is a real attribute named exactly "Tamaño de la
    pantalla" (same as Falabella's spec) but is `number_unit`, which needs
    a structured {number, unit} shape this can't safely guess from free
    text — must not match it."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_MCO118449_ATTRIBUTES)

    specifications = (("Tamaño de la pantalla", "1.34"),)
    with _client(handler) as client:
        matched = category_lookup.match_specifications("MCO118449", specifications, client=client)

    assert matched == []


def test_match_specifications_ignores_accents_and_case() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_MCO118449_ATTRIBUTES)

    specifications = (("TIPO DE PANTALLA", "Amoled"),)
    with _client(handler) as client:
        matched = category_lookup.match_specifications("MCO118449", specifications, client=client)

    assert matched == [{"id": "DISPLAY_TYPE", "value_name": "Amoled"}]


def test_match_specifications_skips_hidden_attributes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_MCO118449_ATTRIBUTES)

    specifications = (("SKU", "ABC123"),)
    with _client(handler) as client:
        matched = category_lookup.match_specifications("MCO118449", specifications, client=client)

    assert matched == []


def test_match_specifications_empty_input_skips_the_api_call() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not call the API with no specifications to match")

    with _client(handler) as client:
        assert category_lookup.match_specifications("MCO118449", (), client=client) == []
