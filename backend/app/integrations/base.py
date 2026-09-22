"""Abstract integration interfaces.

Two families of adapters:

- `SourceAdapter`: a place products can be bought (supplier, retailer,
  scraped marketplace, etc).
- `MarketplaceAdapter`: a place products can be sold (MercadoLibre,
  Shopify, etc).

Concrete implementations MUST NOT invent API behavior. If a method
requires real credentials/API documentation that we don't have yet, it
must raise `NotImplementedError` (or be marked with a TODO) rather than
faking a response. The core arbitrage engine only depends on these
interfaces, never on a specific integration, so new sources/marketplaces
can be added without touching engine code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceProductInfo:
    external_id: str
    name: str
    price: Decimal
    currency: str
    stock_available: bool
    url: str | None = None
    raw: dict[str, Any] | None = None
    # A real reference/list price the source itself reports (e.g. a
    # retailer's crossed-out "normal price" next to a discounted one) —
    # None when the source has no such concept (e.g. a wholesale supplier
    # like CJdropshipping, where `discovery.run_discovery` falls back to
    # its estimated-multiplier heuristic instead). When present, this is
    # real market data and should be preferred over a guessed markup — see
    # PROJECT_CONTEXT.md's 2026-09-22 Falabella finding for why applying a
    # wholesale-arbitrage multiplier to an already-retail price is wrong.
    reference_price: Decimal | None = None
    # Real product photo URLs reported by the source itself (not a stock/
    # placeholder image). None or empty when the source has no usable
    # photo — callers that need a picture (e.g. MercadoLibre's "free"
    # listing type effectively requires one) must handle that case rather
    # than assume it's always present.
    image_urls: tuple[str, ...] = ()


class SourceAdapter(ABC):
    """Interface every supplier/source integration must implement."""

    @abstractmethod
    def search_products(self, query: str, limit: int = 20) -> list[SourceProductInfo]:
        """Search the source's catalog for products matching a free-text query."""

    @abstractmethod
    def get_product(self, external_id: str) -> SourceProductInfo | None:
        """Fetch a single product by its source-specific external id."""

    @abstractmethod
    def get_price(self, external_id: str) -> Decimal | None:
        """Fetch the current price for a product."""

    @abstractmethod
    def get_stock(self, external_id: str) -> bool:
        """Return whether the product currently has stock available."""

    @abstractmethod
    def get_product_url(self, external_id: str) -> str | None:
        """Return the public URL for the product on this source, if any."""


@dataclass(frozen=True, slots=True)
class MarketplaceListingInfo:
    external_id: str
    title: str
    price: Decimal
    currency: str
    status: str
    url: str | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class MarketplaceOrderInfo:
    external_id: str
    status: str
    total_amount: Decimal
    currency: str
    raw: dict[str, Any] | None = None


class MarketplaceAdapter(ABC):
    """Interface every marketplace/selling-channel integration must implement."""

    @abstractmethod
    def authenticate(self) -> bool:
        """Perform whatever auth handshake the marketplace requires.
        Returns True on success, False if credentials are missing/invalid."""

    @abstractmethod
    def search_products(self, query: str, limit: int = 20) -> list[MarketplaceListingInfo]:
        """Search existing marketplace listings/catalog for a query."""

    @abstractmethod
    def get_product(self, external_id: str) -> MarketplaceListingInfo | None:
        """Fetch marketplace catalog info for a product."""

    @abstractmethod
    def get_listing(self, external_id: str) -> MarketplaceListingInfo | None:
        """Fetch our own listing for a product."""

    @abstractmethod
    def create_listing(
        self, product_id: str, title: str, price: Decimal, currency: str
    ) -> MarketplaceListingInfo:
        """Publish a new listing."""

    @abstractmethod
    def update_listing(self, external_id: str, **fields: Any) -> MarketplaceListingInfo:
        """Update fields on an existing listing."""

    @abstractmethod
    def update_price(self, external_id: str, price: Decimal) -> None:
        """Update the selling price of an existing listing."""

    @abstractmethod
    def update_stock(self, external_id: str, in_stock: bool) -> None:
        """Update stock/availability status of an existing listing."""

    @abstractmethod
    def get_orders(self, since: str | None = None) -> list[MarketplaceOrderInfo]:
        """Fetch orders placed on this marketplace, optionally since a timestamp."""
