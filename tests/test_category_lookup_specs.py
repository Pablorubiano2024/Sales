"""Tests for the 2026-10-15 additions to category_lookup.match_specifications:
number_unit attributes, "|"-separated / synonym / volt values, and GTIN
check-digit validation. Attribute shapes copied from real
/categories/{id}/attributes responses (MCO14903 TVs, MCO115340 vacuums)."""

from __future__ import annotations

import httpx

from backend.app.services import category_lookup

ATTRS = [
    {
        "id": "DISPLAY_SIZE",
        "name": "Tamaño de la pantalla",
        "value_type": "number_unit",
        "allowed_units": [{"id": '"', "name": '"'}],
        "tags": {"required": True},
    },
    {
        "id": "VOLTAGE",
        "name": "Voltaje",
        "value_type": "string",
        "values": [{"name": "110V"}, {"name": "110/220V"}],
        "tags": {},
    },
    {
        "id": "COLOR",
        "name": "Color",
        "value_type": "string",
        "values": [{"name": "Azul"}, {"name": "Negro"}],
        "tags": {},
    },
    {
        "id": "POWER_SUPPLY_TYPE",
        "name": "Tipo de alimentación",
        "value_type": "string",
        "values": [{"name": "Batería"}, {"name": "Corriente doméstica"}],
        "tags": {},
    },
]


def _client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ATTRS)

    return httpx.Client(
        base_url="https://api.mercadolibre.com", transport=httpx.MockTransport(handler)
    )


def _match(*specs: tuple[str, str]) -> dict[str, str]:
    with _client() as client:
        result = category_lookup.match_specifications("MCOX", specs, client=client)
    return {a["id"]: a["value_name"] for a in result}


def test_display_size_from_bare_number_with_single_unit() -> None:
    assert _match(("Tamaño de la pantalla", "50")) == {"DISPLAY_SIZE": '50 "'}
    assert _match(("Tamaño de la pantalla", "43 pulgadas")) == {"DISPLAY_SIZE": '43 "'}


def test_display_size_rejects_unknown_unit_or_text() -> None:
    assert _match(("Tamaño de la pantalla", "127 cm")) == {}
    assert _match(("Tamaño de la pantalla", "Grande")) == {}


def test_alkosto_style_values() -> None:
    assert _match(
        ("Voltaje", "Rango entre 110 V y 120 V"),
        ("Color", "Azul|Negro"),
        ("Fuentes de Alimentacion de Energia", "Energía Eléctrica"),
    ) == {"VOLTAGE": "110V", "COLOR": "Azul", "POWER_SUPPLY_TYPE": "Corriente doméstica"}
    assert _match(("Fuentes de Alimentacion de Energia", "Batería Recargable Interna")) == {
        "POWER_SUPPLY_TYPE": "Batería"
    }


def test_gtin_check_digit() -> None:
    assert category_lookup.is_valid_gtin("8806096656419")  # LG XBOOM Mini, Alkosto
    assert category_lookup.is_valid_gtin("7705946652742")  # Kalley, Alkosto
    assert not category_lookup.is_valid_gtin("8806096656418")
    assert not category_lookup.is_valid_gtin("1200130037597x")
