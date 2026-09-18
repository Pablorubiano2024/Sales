"""CJdropshipping supplier adapter — a REAL, verified integration.

Unlike `dropi.py` (skeleton, unverified) this is built against official
documentation the user pulled directly from their own CJdropshipping
account (Get API Key page), cross-checked live before writing this file
(2026-09-17):

  POST /api2.0/v1/authentication/getAccessToken
      body: {"apiKey": "CJUserNum@api@..."}  (from CJ's Apps -> API app ->
      "Get API Key" page — NOT email/password; an earlier version of this
      file used email+password based on a third-party doc mirror that
      turned out to be outdated, caught by live-testing this exact call)
      -> {"data": {"openId", "accessToken", "accessTokenExpiryDate"
           (180 days), "refreshToken", "refreshTokenExpiryDate"
           (180 days), "createDate"}}
      Confirmed live: a malformed apiKey returns
      {"code": 1600005, "message": "APIkey is wrong, please check and
      try again"} — real validation, not invented.

  POST /api2.0/v1/authentication/refreshAccessToken
      body: {"refreshToken": "..."}  -> same shape as getAccessToken.
      Not implemented here yet (access tokens last 180 days, well beyond
      this process's lifetime) — add if a long-lived worker needs it.

  GET /api2.0/v1/product/listV2?keyWord=&page=&size=
      header: CJ-Access-Token: <accessToken>
      -> {"data": {"content": [{"productList": [{id, nameEn, sellPrice,
           sku, bigImage, warehouseInventoryNum}, ...]}]}}
      Confirmed live: no/invalid token returns
      {"message": "access token cannot be empty"}.

  GET /api2.0/v1/product/query?pid=<id>
      header: CJ-Access-Token: <accessToken>
      -> {"data": {pid, productNameEn, sellPrice, productSku, bigImage,
           variants: [{vid, variantSku, variantSellPrice,
           inventories: [{countryCode, totalInventory, ...}]}]}}

CJdropshipping is a China-based global dropshipping supplier (not a
Colombian one like Dropi) — shipping times to Colombia are longer than a
local supplier's. It's used here because it has a genuinely self-serve,
publicly documented API (create an account, generate an API Key yourself
— no partner/white-label approval needed), unlike Dropi as of this
writing (see PROJECT_CONTEXT.md).

Rate limit per CJ's own docs: 1 request/second. This adapter does not
implement client-side throttling (MVP) — a future scheduled job (see
backend/app/jobs/) should pace calls if it fans out across many products.

CJ does not document a public per-product storefront URL in the search/
detail response fields above, so `get_product_url` returns None rather
than guessing one.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.integrations.base import SourceAdapter, SourceProductInfo

logger = get_logger(__name__)

BASE_URL = "https://developers.cjdropshipping.com"
DEFAULT_TIMEOUT = 15.0


class CJDropshippingAdapter(SourceAdapter):
    """Source adapter for CJdropshipping's real, documented API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key or settings.cj_api_key
        self._client = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)
        self._access_token: str | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> CJDropshippingAdapter:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def _login(self) -> str | None:
        if not self.is_configured():
            logger.info("CJdropshipping not configured (CJ_API_KEY unset).")
            return None
        try:
            response = self._client.post(
                "/api2.0/v1/authentication/getAccessToken",
                json={"apiKey": self._api_key},
            )
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("CJdropshipping login failed: %s", exc)
            return None

        if not payload.get("result"):
            logger.warning("CJdropshipping login rejected: %s", payload.get("message"))
            return None

        token = payload.get("data", {}).get("accessToken")
        self._access_token = token
        return token

    def _headers(self) -> dict[str, str] | None:
        token = self._access_token or self._login()
        if token is None:
            return None
        return {"CJ-Access-Token": token}

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any] | None:
        headers = self._headers()
        if headers is None:
            return None
        try:
            response = self._client.get(path, params=params, headers=headers)
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("CJdropshipping GET %s failed: %s", path, exc)
            return None

        # Token may have expired; retry once with a fresh login.
        if payload.get("code") == 1600002 and self._access_token is not None:
            self._access_token = None
            headers = self._headers()
            if headers is None:
                return None
            try:
                response = self._client.get(path, params=params, headers=headers)
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("CJdropshipping GET %s retry failed: %s", path, exc)
                return None

        if not payload.get("result"):
            logger.warning("CJdropshipping GET %s rejected: %s", path, payload.get("message"))
            return None
        return payload.get("data")

    def _parse_list_item(self, item: dict[str, Any]) -> SourceProductInfo | None:
        try:
            price = Decimal(str(item["sellPrice"]))
        except (KeyError, InvalidOperation):
            logger.warning("CJdropshipping product %s has an unparseable price", item.get("id"))
            return None
        return SourceProductInfo(
            external_id=str(item["id"]),
            name=item.get("nameEn", f"Product {item['id']}"),
            price=price,
            currency="USD",
            stock_available=bool(item.get("warehouseInventoryNum", 0)),
            url=None,  # CJ's docs don't expose a public storefront URL here.
            raw=item,
        )

    def _parse_detail(self, data: dict[str, Any]) -> SourceProductInfo | None:
        try:
            price = Decimal(str(data["sellPrice"]))
        except (KeyError, InvalidOperation):
            logger.warning("CJdropshipping product %s has an unparseable price", data.get("pid"))
            return None

        total_inventory = sum(
            inv.get("totalInventory", 0)
            for variant in data.get("variants", [])
            for inv in variant.get("inventories", [])
        )

        return SourceProductInfo(
            external_id=str(data["pid"]),
            name=data.get("productNameEn", f"Product {data['pid']}"),
            price=price,
            currency="USD",
            stock_available=total_inventory > 0,
            url=None,
            raw=data,
        )

    def search_products(self, query: str, limit: int = 20) -> list[SourceProductInfo]:
        data = self._get(
            "/api2.0/v1/product/listV2",
            {"keyWord": query, "page": 1, "size": min(limit, 100)},
        )
        if data is None:
            return []
        items = [
            product for page in data.get("content", []) for product in page.get("productList", [])
        ]
        parsed = [self._parse_list_item(item) for item in items[:limit]]
        return [p for p in parsed if p is not None]

    def get_product(self, external_id: str) -> SourceProductInfo | None:
        data = self._get("/api2.0/v1/product/query", {"pid": external_id})
        if data is None:
            return None
        return self._parse_detail(data)

    def get_price(self, external_id: str) -> Decimal | None:
        product = self.get_product(external_id)
        return product.price if product else None

    def get_stock(self, external_id: str) -> bool:
        product = self.get_product(external_id)
        return bool(product and product.stock_available)

    def get_product_url(self, external_id: str) -> str | None:
        # Not documented by CJ's API — see module docstring.
        return None
