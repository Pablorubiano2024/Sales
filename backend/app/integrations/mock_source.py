"""Mock supplier/source adapter.

This is a clearly-fake, in-memory source used for local development,
demos and tests. It does NOT talk to any real supplier. It exists so the
discovery/pricing pipeline can be exercised end-to-end before any real
source integration is wired in.
"""

from __future__ import annotations

from decimal import Decimal

from backend.app.integrations.base import SourceAdapter, SourceProductInfo

# Small fictional catalog. Clearly test/demo data, not scraped from anywhere.
_MOCK_CATALOG: dict[str, SourceProductInfo] = {
    "MOCK-001": SourceProductInfo(
        external_id="MOCK-001",
        name="Wireless Bluetooth Headphones",
        price=Decimal("45000"),
        currency="COP",
        stock_available=True,
        url="https://mock-supplier.example.com/products/MOCK-001",
    ),
    "MOCK-002": SourceProductInfo(
        external_id="MOCK-002",
        name="USB-C 7-in-1 Hub",
        price=Decimal("38000"),
        currency="COP",
        stock_available=True,
        url="https://mock-supplier.example.com/products/MOCK-002",
    ),
    "MOCK-003": SourceProductInfo(
        external_id="MOCK-003",
        name="Adjustable Aluminum Laptop Stand",
        price=Decimal("32000"),
        currency="COP",
        stock_available=True,
        url="https://mock-supplier.example.com/products/MOCK-003",
    ),
    "MOCK-004": SourceProductInfo(
        external_id="MOCK-004",
        name="LED Desk Lamp with Wireless Charger",
        price=Decimal("52000"),
        currency="COP",
        stock_available=False,
        url="https://mock-supplier.example.com/products/MOCK-004",
    ),
    "MOCK-005": SourceProductInfo(
        external_id="MOCK-005",
        name="Portable Rechargeable Blender",
        price=Decimal("61000"),
        currency="COP",
        stock_available=True,
        url="https://mock-supplier.example.com/products/MOCK-005",
    ),
}


class MockSourceAdapter(SourceAdapter):
    """Fake source backed by an in-memory catalog. Development/testing only."""

    def __init__(self, catalog: dict[str, SourceProductInfo] | None = None) -> None:
        self._catalog = catalog if catalog is not None else _MOCK_CATALOG

    def search_products(self, query: str, limit: int = 20) -> list[SourceProductInfo]:
        query_lower = query.lower()
        matches = [item for item in self._catalog.values() if query_lower in item.name.lower()]
        return matches[:limit]

    def get_product(self, external_id: str) -> SourceProductInfo | None:
        return self._catalog.get(external_id)

    def get_price(self, external_id: str) -> Decimal | None:
        item = self._catalog.get(external_id)
        return item.price if item else None

    def get_stock(self, external_id: str) -> bool:
        item = self._catalog.get(external_id)
        return bool(item and item.stock_available)

    def get_product_url(self, external_id: str) -> str | None:
        item = self._catalog.get(external_id)
        return item.url if item else None
