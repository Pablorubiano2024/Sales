"""Tests for category_lookup.py using httpx.MockTransport — response
shapes match domain_discovery/categories-attributes verified live
2026-09-22 (see module docstring)."""

from __future__ import annotations

import json
from decimal import Decimal

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


def test_is_safe_to_autopublish_true_when_extra_attribute_is_covered() -> None:
    """2026-10-03 fix: a required attribute beyond BRAND/MODEL is fine
    when the caller already confirmed match_specifications matched it for
    this specific product — this is what let real categories (TVs,
    neveras, lavadoras...) stop being blocked wholesale."""

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
        assert (
            category_lookup.is_safe_to_autopublish(
                "MCO412089",
                client=client,
                extra_covered_ids=frozenset({"POWER_SUPPLY_TYPE"}),
            )
            is True
        )


def test_is_safe_to_autopublish_false_when_only_some_extra_attributes_covered() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"id": "BRAND", "tags": {"required": True}},
                {"id": "MODEL", "tags": {"required": True}},
                {"id": "POWER_SUPPLY_TYPE", "tags": {"required": True}},
                {"id": "GTIN", "tags": {"required": False, "conditional_required": True}},
            ],
        )

    with _client(handler) as client:
        assert (
            category_lookup.is_safe_to_autopublish(
                "MCO412089",
                client=client,
                extra_covered_ids=frozenset({"POWER_SUPPLY_TYPE"}),
            )
            is False
        )


def test_real_conditional_required_ids_posts_brand_and_model() -> None:
    """Real shape confirmed live 2026-10-03: POST
    /categories/{id}/attributes/conditional with condition + BRAND/MODEL
    -> {"required_attributes": [...]}. Public, no auth header sent."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/categories/MCO456045/attributes/conditional"
        body = json.loads(request.content)
        assert body["condition"] == "new"
        assert {"id": "BRAND", "value_name": "Electrolux"} in body["attributes"]
        assert {"id": "MODEL", "value_name": "EAF50"} in body["attributes"]
        return httpx.Response(
            200,
            json={
                "required_attributes": [{"id": "GTIN", "name": "Código universal de producto"}],
                "callbacks": [],
                "status": 200,
            },
        )

    with _client(handler) as client:
        result = category_lookup.real_conditional_required_ids(
            "MCO456045", brand="Electrolux", model="EAF50", client=client
        )

    assert result == ["GTIN"]


def test_real_conditional_required_ids_none_on_http_error() -> None:
    """None (not []) on failure — "we don't know" must never be read as
    "nothing required"."""
    with _client(lambda r: httpx.Response(500)) as client:
        result = category_lookup.real_conditional_required_ids(
            "MCO456045", brand="Electrolux", model="EAF50", client=client
        )
    assert result is None


def test_required_attribute_ids_resolves_conditional_gtin_per_real_brand() -> None:
    """Confirmed live 2026-10-03: GTIN's real requirement is brand-
    specific, not a blanket per-category flag — KALLEY freidoras don't
    need it even though GTIN is conditional_required on the category."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"required_attributes": []})
        return httpx.Response(
            200,
            json=[
                {"id": "BRAND", "tags": {"required": True}},
                {"id": "MODEL", "tags": {"required": True}},
                {"id": "GTIN", "tags": {"conditional_required": True}},
            ],
        )

    with _client(handler) as client:
        required = category_lookup.required_attribute_ids(
            "MCO456045", client=client, brand="KALLEY", model="K-MAF35"
        )
        assert "GTIN" not in required
        assert (
            category_lookup.is_safe_to_autopublish(
                "MCO456045", client=client, brand="KALLEY", model="K-MAF35"
            )
            is True
        )


def test_required_attribute_ids_falls_back_to_blocking_when_real_check_fails() -> None:
    """If the real per-item check can't be reached, GTIN must still
    block — never silently assume it's fine."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(500)
        return httpx.Response(
            200,
            json=[
                {"id": "BRAND", "tags": {"required": True}},
                {"id": "MODEL", "tags": {"required": True}},
                {"id": "GTIN", "tags": {"conditional_required": True}},
            ],
        )

    with _client(handler) as client:
        required = category_lookup.required_attribute_ids(
            "MCO456045", client=client, brand="KALLEY", model="K-MAF35"
        )
        assert "GTIN" in required


def test_required_attribute_ids_includes_conditional_required() -> None:
    """Real bug found live 2026-10-01: GTIN's real tags for category
    MCO456045 are {"required": False, "conditional_required": True} — a
    real create_listing attempt still failed with
    item.attribute.missing_conditional_required. Exact real shape, not
    guessed."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"id": "BRAND", "tags": {"required": True}},
                {"id": "MODEL", "tags": {"required": True}},
                {
                    "id": "GTIN",
                    "tags": {
                        "multivalued": True,
                        "variation_attribute": True,
                        "used_hidden": True,
                        "validate": True,
                        "conditional_required": True,
                    },
                },
            ],
        )

    with _client(handler) as client:
        required = category_lookup.required_attribute_ids("MCO456045", client=client)
        assert "GTIN" in required
        assert category_lookup.is_safe_to_autopublish("MCO456045", client=client) is False


def test_required_attribute_ids_excludes_new_hidden_attributes() -> None:
    """Real bug found live 2026-10-03: GRADING is conditional_required on
    nearly every real category (TVs, neveras, parlantes, freidoras...)
    but its own real tags include new_hidden: true — MercadoLibre doesn't
    apply it to a condition="new" item, which is the only condition
    create_listing() here ever publishes. Treating it as blocking anyway
    was wrong, not conservative — it was skipping real categories
    (parlantes: MCO3691/MCO11860) that have NO other required attribute
    beyond BRAND/MODEL/GTIN once this is excluded."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"id": "BRAND", "tags": {"required": True}},
                {"id": "MODEL", "tags": {"required": True}},
                {
                    "id": "GRADING",
                    "tags": {
                        "used_hidden": True,
                        "conditional_required": True,
                        "new_hidden": True,
                        "open_box_hidden": True,
                    },
                },
            ],
        )

    with _client(handler) as client:
        required = category_lookup.required_attribute_ids("MCO3691", client=client)
        assert "GRADING" not in required
        assert category_lookup.is_safe_to_autopublish("MCO3691", client=client) is True


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


_LISTING_PRICES_RESPONSE = [
    {"listing_type_id": "gold_pro", "sale_fee_amount": 100000},
    {"listing_type_id": "gold_special", "sale_fee_amount": 82500},
    {"listing_type_id": "free", "sale_fee_amount": 0},
]


def test_get_sale_commission_pct_computes_the_real_fraction() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/sites/MCO/listing_prices"
        assert request.url.params["price"] == "500000"
        assert request.url.params["category_id"] == "MCO456045"
        assert request.headers["authorization"] == "Bearer tok"
        return httpx.Response(200, json=_LISTING_PRICES_RESPONSE)

    with _client(handler) as client:
        pct = category_lookup.get_sale_commission_pct(
            "MCO456045", Decimal("500000"), client=client, access_token="tok"
        )

    assert pct == Decimal("0.1650")


def test_get_sale_commission_pct_respects_listing_type_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_LISTING_PRICES_RESPONSE)

    with _client(handler) as client:
        pct = category_lookup.get_sale_commission_pct(
            "MCO456045",
            Decimal("500000"),
            client=client,
            access_token="tok",
            listing_type_id="free",
        )

    assert pct == Decimal("0.0000")


def test_get_sale_commission_pct_returns_none_when_type_not_offered() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_LISTING_PRICES_RESPONSE)

    with _client(handler) as client:
        pct = category_lookup.get_sale_commission_pct(
            "MCO456045",
            Decimal("500000"),
            client=client,
            access_token="tok",
            listing_type_id="silver",
        )

    assert pct is None


def test_get_sale_commission_pct_returns_none_on_http_error() -> None:
    with _client(lambda r: httpx.Response(403)) as client:
        pct = category_lookup.get_sale_commission_pct(
            "MCO456045", Decimal("500000"), client=client, access_token="tok"
        )

    assert pct is None


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


_BOUNDED_ATTRIBUTES = [
    {
        "id": "WRISTBAND_MATERIAL",
        "name": "Material de la malla",
        "value_type": "string",
        "tags": {},
        "values": [{"id": "1", "name": "Silicona"}, {"id": "2", "name": "Cuero"}],
    },
    {
        "id": "WITH_BLUETOOTH",
        "name": "Con Bluetooth",
        "value_type": "boolean",
        "tags": {},
        "values": [{"id": "1", "name": "Sí"}, {"id": "2", "name": "No"}],
    },
    {
        "id": "SMARTWATCH_COMPATIBLE_OS",
        "name": "Sistemas operativos compatibles del smartwatch",
        "value_type": "string",
        "tags": {"multivalued": True},
        "values": [{"id": "1", "name": "Android"}, {"id": "2", "name": "iOS"}],
    },
]


def test_match_specifications_validates_against_real_bounded_values() -> None:
    """WRISTBAND_MATERIAL has value_type "string" but a real, bounded
    vocabulary (verified live 2026-09-25) — a matching real value should
    be accepted using the list's own canonical casing."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_BOUNDED_ATTRIBUTES)

    specifications = (("Material de la malla", "silicona"),)  # lowercase, real casing differs
    with _client(handler) as client:
        matched = category_lookup.match_specifications("MCO118449", specifications, client=client)

    assert matched == [{"id": "WRISTBAND_MATERIAL", "value_name": "Silicona"}]


def test_match_specifications_rejects_value_not_in_bounded_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_BOUNDED_ATTRIBUTES)

    specifications = (("Material de la malla", "Titanio"),)  # not a real option
    with _client(handler) as client:
        matched = category_lookup.match_specifications("MCO118449", specifications, client=client)

    assert matched == []


def test_match_specifications_uses_known_synonym_for_confirmed_name_mismatch() -> None:
    """Falabella's "Material de la correa" and MercadoLibre's
    "Material de la malla" (WRISTBAND_MATERIAL) are the same real concept
    under different names — confirmed live 2026-09-25."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_BOUNDED_ATTRIBUTES)

    specifications = (("Material de la correa", "Silicona"),)
    with _client(handler) as client:
        matched = category_lookup.match_specifications("MCO118449", specifications, client=client)

    assert matched == [{"id": "WRISTBAND_MATERIAL", "value_name": "Silicona"}]


def test_match_specifications_skips_multivalued_attributes() -> None:
    """Submission shape for a multivalued attribute (e.g. multiple
    compatible OSes) isn't confirmed — must not guess it."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_BOUNDED_ATTRIBUTES)

    specifications = (("Sistemas operativos compatibles del smartwatch", "Android"),)
    with _client(handler) as client:
        matched = category_lookup.match_specifications("MCO118449", specifications, client=client)

    assert matched == []


def test_match_specifications_matches_boolean_value_from_yes_no_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_BOUNDED_ATTRIBUTES)

    specifications = (("Con Bluetooth", "sí"),)
    with _client(handler) as client:
        matched = category_lookup.match_specifications("MCO118449", specifications, client=client)

    assert matched == [{"id": "WITH_BLUETOOTH", "value_name": "Sí"}]


_APPLIANCE_ATTRIBUTES = [
    {
        "id": "DISPLAY_SIZE",
        "name": "Tamaño de la pantalla",
        "value_type": "number_unit",
        "allowed_units": [{"id": '"', "name": '"'}],
    },
    {
        "id": "WASHING_MACHINE_CAPACITY",
        "name": "Capacidad de la lavadora",
        "value_type": "number_unit",
        "allowed_units": [{"id": "kg", "name": "kg"}, {"id": "lb", "name": "lb"}],
    },
    {
        "id": "VOLUME_CAPACITY",
        "name": "Capacidad en volumen",
        "value_type": "number_unit",
        "allowed_units": [{"id": "L", "name": "L"}, {"id": "mL", "name": "mL"}],
    },
    {
        "id": "LOADING_TYPE",
        "name": "Tipo de carga",
        "value_type": "list",
        "values": [{"name": "Frontal"}, {"name": "Superior"}],
    },
    {
        "id": "WASHING_MACHINE_TYPE",
        "name": "Tipo de lavadora",
        "value_type": "list",
        "values": [{"name": "Automática"}, {"name": "Semi-automática"}],
    },
    {
        "id": "COLOR",
        "name": "Color",
        "value_type": "string",
        "values": [{"name": "Negro"}, {"name": "Gris"}, {"name": "Azul"}, {"name": "Azul oscuro"}],
    },
    {"id": "VOLTAGE", "name": "Voltaje", "value_type": "string", "values": [{"name": "110V"}]},
    {
        "id": "POWER_SUPPLY_TYPE",
        "name": "Tipo de alimentación",
        "value_type": "string",
        "values": [{"name": "Batería"}, {"name": "Corriente doméstica"}],
    },
    {
        "id": "FAN_TYPE",
        "name": "Tipo de ventilador",
        "value_type": "string",
        "values": [{"name": "De torre"}, {"name": "De pared"}],
    },
    {
        "id": "IS_FACTORY_KIT",
        "name": "Es kit",
        "value_type": "boolean",
        "values": [{"name": "No"}, {"name": "Sí"}],
    },
    {
        "id": "CONNECTOR_TYPE",
        "name": "Tipo de conector",
        "value_type": "string",
        "values": [{"name": "USB"}, {"name": "Micro-USB"}, {"name": "USB-C"}],
    },
]


def _infer(name: str, specs: tuple[tuple[str, str], ...], ids: list[str]) -> dict[str, str]:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_APPLIANCE_ATTRIBUTES)

    with _client(handler) as client:
        found = category_lookup.infer_from_listing("MCO1", name, specs, ids, client=client)
    return {a["id"]: a["value_name"] for a in found}


def test_infer_reads_sizes_and_capacities_from_the_title() -> None:
    ids = ["DISPLAY_SIZE", "WASHING_MACHINE_CAPACITY", "VOLUME_CAPACITY"]
    assert _infer('TV LG 55" Pulgadas 139 Cm 55LX7BPSA', (), ids[:1]) == {"DISPLAY_SIZE": '55 "'}
    assert _infer("Lavadora LG Carga Frontal 20 Kilos WM20", (), ids[1:2]) == {
        "WASHING_MACHINE_CAPACITY": "20 kg"
    }
    assert _infer("Nevera LG No Frost 461 Litros GB45SPP", (), ids[2:]) == {
        "VOLUME_CAPACITY": "461 L"
    }


def test_infer_washer_loading_and_type() -> None:
    ids = ["LOADING_TYPE", "WASHING_MACHINE_TYPE"]
    assert _infer("Lavadora LG Carga Frontal 20 Kilos", (), ids) == {
        "LOADING_TYPE": "Frontal",
        "WASHING_MACHINE_TYPE": "Automática",
    }
    assert _infer("Lavadora Acros SemiAutomatica Carga Superior 10KG", (), ids) == {
        "LOADING_TYPE": "Superior",
        "WASHING_MACHINE_TYPE": "Semi-automática",
    }
    # A top loader that doesn't say which: left missing, not guessed.
    assert _infer("Lavadora KALLEY Carga Superior 16 Kilos", (), ids) == {
        "LOADING_TYPE": "Superior"
    }


def test_infer_color_only_when_one_is_named() -> None:
    assert _infer("Aspiradora Dreame E10 Negra", (), ["COLOR"]) == {"COLOR": "Negro"}
    assert _infer("Lavadora LG", (("Color", 'Silver "Gris tipo acero"'),), ["COLOR"]) == {
        "COLOR": "Gris"
    }
    assert _infer("Licuadora Azul oscuro", (), ["COLOR"]) == {"COLOR": "Azul oscuro"}
    assert _infer("Aspiradora Powerspeed Gris/Azul", (), ["COLOR"]) == {}


def test_infer_voltage_and_power_supply_from_where_we_buy() -> None:
    assert _infer('TV LG 55"', (), ["VOLTAGE"]) == {"VOLTAGE": "110V"}
    assert _infer("Secadora 220V", (), ["VOLTAGE"]) == {}
    corded = (("Potencia", "1400 W"),)
    assert _infer("Licuadora Ninja", corded, ["POWER_SUPPLY_TYPE"]) == {
        "POWER_SUPPLY_TYPE": "Corriente doméstica"
    }
    assert _infer("Aspiradora Robot Xiaomi 2000 W", (), ["POWER_SUPPLY_TYPE"]) == {}
    assert _infer("Licuadora Ninja", (), ["POWER_SUPPLY_TYPE"]) == {}


def test_infer_plug_in_devices_kits_and_usb_c() -> None:
    power = ["POWER_SUPPLY_TYPE"]
    assert _infer("Video beam Qxk Full Hd 1080p 7500 Lumens", (), power) == {
        "POWER_SUPPLY_TYPE": "Corriente doméstica"
    }
    assert _infer("Proyector Portatil Freestyle", (), power) == {}
    assert _infer("Mini Proyector con batería", (), power) == {}
    kit = ["IS_FACTORY_KIT"]
    assert _infer("Kit de Micrófonos Inalámbricos Creators", (), kit) == {"IS_FACTORY_KIT": "Sí"}
    assert _infer("Micrófono Inalámbrico Solapa", (), kit) == {}
    usb = ["CONNECTOR_TYPE"]
    assert _infer("Power Bank 20000mAh Carga Rápida USB-C", (), usb) == {"CONNECTOR_TYPE": "USB-C"}
    assert _infer("Power Bank USB-C y Micro USB", (), usb) == {}


def test_match_specifications_new_source_wordings() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_APPLIANCE_ATTRIBUTES)

    specifications = (
        ("Tamaño Pantalla", "65 Pulgadas"),
        ("Tipo de Alimentacion de La lavadora", "Energía Eléctrica"),
        ("Capacidad Carga Lavado", "22 Libras"),
        ("Tipo de ventilador", "Torre"),
    )
    with _client(handler) as client:
        matched = category_lookup.match_specifications("MCO1", specifications, client=client)
    assert {a["id"]: a["value_name"] for a in matched} == {
        "DISPLAY_SIZE": '65 "',
        "POWER_SUPPLY_TYPE": "Corriente doméstica",
        "WASHING_MACHINE_CAPACITY": "22 lb",
        "FAN_TYPE": "De torre",
    }
