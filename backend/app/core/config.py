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

    # --- Database ---
    database_url: str = "sqlite:///./data/arbitrage.db"

    # --- Claude / Anthropic ---
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"

    # --- Arbitrage thresholds (defaults; configurable, never hard-coded inline) ---
    min_roi: Decimal = Decimal("0.30")
    min_net_profit: Decimal = Decimal("20000")
    max_risk_score: float = 0.50

    # --- Currency ---
    default_currency: str = "COP"

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
