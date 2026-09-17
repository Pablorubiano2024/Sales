from __future__ import annotations

from fastapi.testclient import TestClient


def test_create_and_get_product(client: TestClient) -> None:
    response = client.post(
        "/api/products",
        json={"sku": "SKU-1", "name": "Wireless Mouse", "category": "Electronics"},
    )
    assert response.status_code == 201
    created = response.json()
    assert created["sku"] == "SKU-1"
    assert created["id"]

    get_response = client.get(f"/api/products/{created['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["name"] == "Wireless Mouse"


def test_create_product_duplicate_sku_conflicts(client: TestClient) -> None:
    payload = {"sku": "SKU-DUP", "name": "Duplicate Product"}
    first = client.post("/api/products", json=payload)
    assert first.status_code == 201

    second = client.post("/api/products", json=payload)
    assert second.status_code == 409


def test_get_missing_product_returns_404(client: TestClient) -> None:
    response = client.get("/api/products/does-not-exist")
    assert response.status_code == 404


def test_list_products(client: TestClient) -> None:
    client.post("/api/products", json={"sku": "SKU-A", "name": "Product A"})
    client.post("/api/products", json={"sku": "SKU-B", "name": "Product B"})

    response = client.get("/api/products")
    assert response.status_code == 200
    skus = {p["sku"] for p in response.json()}
    assert {"SKU-A", "SKU-B"}.issubset(skus)
