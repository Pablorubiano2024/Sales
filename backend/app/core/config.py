"""Application configuration loaded from environment variables / .env."""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root: .../Sales (three levels up from this file: core -> app -> backend -> root)
BASE_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Central application settings.

    All values can be overridden via environment variables or a `.env` file
    at the project root. Nothing here is hard-coded elsewhere in the code.
    """

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- General ---
    app_env: str = "development"
    app_name: str = "Product Arbitrage Platform"

    # --- API server ---
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # --- Auth ---
    # When unset, all /api/* endpoints are open (fine for local-only use).
    # Set it to require an `X-API-Key` header matching this value — do this
    # before deploying anywhere reachable beyond localhost.
    api_auth_token: str | None = None

    # --- Database ---
    database_url: str = "sqlite:///./data/arbitrage.db"

    # --- Claude / Anthropic ---
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"

    # --- Dropi (supplier) ---
    # Not yet integrated for real — see backend/app/integrations/dropi.py.
    dropi_integration_key: str | None = None

    # --- MercadoLibre (marketplace) ---
    # Real OAuth2 app, registered at developers.mercadolibre.com.co/devcenter
    # (the docs site's "Mis aplicaciones" link only works from there, not
    # from the regular API-docs pages). See
    # backend/app/integrations/mercadolibre.py and backend/app/api/
    # mercadolibre_oauth.py for the flow.
    ml_client_id: str | None = None
    ml_client_secret: str | None = None
    # Must exactly match one of the Redirect URIs registered for the app —
    # no query string / variable parts allowed.
    ml_redirect_uri: str | None = None

    # --- CJdropshipping (supplier) ---
    # Real, verified self-serve API (developers.cjdropshipping.com). Generate
    # the key from your CJ account: Apps -> install "API" -> Get API Key page.
    cj_api_key: str | None = None

    # --- Arbitrage thresholds (defaults; configurable, never hard-coded inline) ---
    min_roi: Decimal = Decimal("0.30")
    min_net_profit: Decimal = Decimal("20000")
    max_risk_score: float = 0.50

    # --- Currency ---
    default_currency: str = "COP"
    # USD -> COP rate used to convert source prices (e.g. CJdropshipping,
    # which quotes in USD) before they reach the COP-denominated thresholds
    # above. Not fetched live (see services/currency.py for why) — update
    # this if it drifts from the official TRM (banrep.gov.co). Default is
    # the TRM as of 2026-09-18 (~3,130-3,150 COP/USD).
    usd_to_cop_rate: Decimal = Decimal("3130")

    # --- Real marketplace + shipping costs applied during discovery ---
    # These were missing from run_discovery until 2026-09-18: opportunities
    # only subtracted buy_price, so "net_profit" was actually gross margin,
    # overstating profitability. Verified live against MercadoLibre
    # Colombia's own help page (mercadolibre.com.co/ayuda): sale commission
    # is 8%-19% depending on category (up to 22% with extra installments) —
    # 15% here is a reasonable single default, not a per-category lookup.
    marketplace_commission_pct: Decimal = Decimal("0.15")
    # Was a guess ($29,000) until verified live 2026-09-18 against CJ's real
    # freight calculator (POST /api2.0/v1/logistic/freightCalculate,
    # CN->CO) for an actual discovered product (770g projector): real
    # options ranged from $20.56 USD/20-60 days (cheapest) to $105.82
    # USD/3-7 days (DHL). $22.58 USD (~$70,700 COP at usd_to_cop_rate) for
    # "CJPacket Latin America Sensitive" (6-12 days — the fastest option
    # that isn't DHL-expensive) is a much more realistic single default
    # than the old guess, though it's still one number standing in for a
    # per-product/per-weight lookup. Update if you have a better estimate,
    # and see the freight calculator for a specific product before trusting
    # this on anything price-sensitive.
    shipping_cost_cop: Decimal = Decimal("70700")

    @property
    def sqlalchemy_database_url(self) -> str:
        """`database_url`, normalized for SQLAlchemy.

        Neon (and other Postgres hosts) hand out `postgres://` or
        `postgresql://` URLs; SQLAlchemy 2.0 needs an explicit driver in the
        scheme, so both get rewritten to `postgresql+psycopg://` (psycopg 3).
        SQLite URLs pass through unchanged.
        """
        url = self.database_url
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+psycopg://", 1)
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url

    @property
    def sqlite_path(self) -> Path | None:
        """Filesystem path for the SQLite DB file, if using SQLite."""
        if not self.database_url.startswith("sqlite"):
            return None
        # sqlite:///./data/arbitrage.db -> ./data/arbitrage.db
        raw_path = self.database_url.split("sqlite:///", 1)[-1]
        path = Path(raw_path)
        if not path.is_absolute():
            path = BASE_DIR / path
        return path


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor. Use this instead of instantiating Settings() directly."""
    return Settings()
