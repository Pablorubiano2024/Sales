"""Tests for Settings.sqlalchemy_database_url (SQLite/Postgres URL handling)."""

from __future__ import annotations

from backend.app.core.config import Settings


def test_sqlite_url_passes_through_unchanged() -> None:
    settings = Settings(database_url="sqlite:///./data/arbitrage.db")
    assert settings.sqlalchemy_database_url == "sqlite:///./data/arbitrage.db"


def test_legacy_postgres_scheme_gets_psycopg_driver() -> None:
    settings = Settings(database_url="postgres://user:pass@host/db?sslmode=require")
    assert (
        settings.sqlalchemy_database_url == "postgresql+psycopg://user:pass@host/db?sslmode=require"
    )


def test_postgresql_scheme_gets_psycopg_driver() -> None:
    settings = Settings(database_url="postgresql://user:pass@host/db?sslmode=require")
    assert (
        settings.sqlalchemy_database_url == "postgresql+psycopg://user:pass@host/db?sslmode=require"
    )


def test_scheme_with_explicit_driver_is_untouched() -> None:
    url = "postgresql+psycopg://user:pass@host/db"
    settings = Settings(database_url=url)
    assert settings.sqlalchemy_database_url == url
