"""Dropi supplier adapter — SKELETON ONLY.

IMPORTANT: This adapter does NOT call the real Dropi API. Dropi
(https://dropi.co) is Colombia's dominant dropshipping platform and its
business model matches this project closely (verified local suppliers,
pay-on-delivery, ship-direct-to-customer) — see PROJECT_CONTEXT.md — but
using it for real requires:

  1. An active Dropi account (register as a "dropshipper" at dropi.co).
  2. Generating a `dropi-integration-key` from the Dropi panel's
     Integrations section, and getting Dropi's own API documentation
     (endpoints, request/response shapes) directly from them — third-party
     doc mirrors found during research were not treated as authoritative
     and were not used to write this file.

Every public method currently raises NotImplementedError with a TODO
pointing at what's missing, so callers fail loudly instead of silently
getting fake data — this codebase must never invent API endpoints or
pretend an integration works when it hasn't been verified.

To make this real:
  1. Add `dropi_integration_key` to `backend.app.core.config.Settings` and
     `.env.example` (read from `DROPI_INTEGRATION_KEY`).
  2. Get Dropi's official API docs and confirm the exact endpoints for
     product search, product detail, price and stock — wire them into
     the methods below, sending the key as the `dropi-integration-key`
     header (per Dropi's own integration panel instructions).
  3. This adapter only needs to implement `SourceAdapter` (read-only
     discovery) for the MVP — the manual "buy from supplier" step stays
     manual per PROJECT_CONTEXT.md's business-model principles. A future
     phase (semi-automated purchasing) may need Dropi's order-creation
     endpoints too; that's out of scope until Phase 7.
"""

from __future__ import annotations

from decimal import Decimal

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.integrations.base import SourceAdapter, SourceProductInfo

logger = get_logger(__name__)


class DropiAdapter(SourceAdapter):
    """Skeleton adapter for Dropi. Not functional yet — see module docstring."""

    def __init__(self) -> None:
        self._settings = get_settings()

    def close(self) -> None:
        """No real resources held yet — no HTTP client built until the
        real API is implemented (see module docstring)."""

    def is_configured(self) -> bool:
        return bool(self._settings.dropi_integration_key)

    def search_products(self, query: str, limit: int = 20) -> list[SourceProductInfo]:
        # TODO: confirm the product search endpoint from Dropi's own docs
        # and send `dropi-integration-key` as a header.
        raise NotImplementedError(
            "Dropi search_products requires an integration key and verified API docs."
        )

    def get_product(self, external_id: str) -> SourceProductInfo | None:
        # TODO: confirm the product detail endpoint.
        raise NotImplementedError(
            "Dropi get_product requires an integration key and verified API docs."
        )

    def get_price(self, external_id: str) -> Decimal | None:
        # TODO: likely part of the product detail response above.
        raise NotImplementedError(
            "Dropi get_price requires an integration key and verified API docs."
        )

    def get_stock(self, external_id: str) -> bool:
        # TODO: likely part of the product detail response above.
        raise NotImplementedError(
            "Dropi get_stock requires an integration key and verified API docs."
        )

    def get_product_url(self, external_id: str) -> str | None:
        # TODO: confirm whether Dropi exposes a public product page URL.
        raise NotImplementedError("Dropi get_product_url requires verified API docs.")
