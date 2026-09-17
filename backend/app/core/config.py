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

    # --- Arbitrage thresholds (defaults; configurable, never hard-coded inline) ---
    min_roi: Decimal = Decimal("0.30")
    min_net_profit: Decimal = Decimal("20000")
    max_risk_score: float = 0.50

    # --- Currency ---
    default_currency: str = "COP"

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
