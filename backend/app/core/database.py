"""SQLAlchemy engine/session setup.

Uses SQLite by default (local/dev). Setting `DATABASE_URL` to a Postgres
connection string (e.g. from Neon) switches to Postgres — no other code
changes needed. `sqlalchemy_database_url` (see core/config.py) normalizes
the scheme so SQLAlchemy picks the psycopg driver explicitly.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.core.config import get_settings

settings = get_settings()

_connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    # Without an explicit bound, a network issue reaching a hosted Postgres
    # (e.g. from a CI runner with a different network path than local dev)
    # can hang the *first* connection attempt indefinitely — pool_pre_ping
    # only protects a connection already established. Confirmed live
    # 2026-09-25: a GitHub Actions discovery run hung 20+ minutes with no
    # error on its very first DB write, while the same script ran normally
    # (a few seconds to connect) from local dev.
    #
    # A short value matters more than it looks here: Neon's hostname
    # resolves to 3 IPv6 addresses *and* 3 IPv4 ones, and confirmed live
    # the same day that this machine's IPv6 route to at least one of them
    # is dead ("No route to host") while IPv4 connects in ~0.1s. libpq
    # tries resolved addresses in order and applies `connect_timeout` per
    # address, so with a 10s timeout, exhausting a couple of broken IPv6
    # addresses before reaching a working IPv4 one reproduced the exact
    # ~30-33s-per-connection delay pattern seen in a hung local run. A
    # tighter bound caps that worst case without disabling IPv6 outright
    # (environments with real IPv6 connectivity, e.g. GitHub Actions
    # runners, keep using it — this doesn't force IPv4-only).
    else {"connect_timeout": 5}
)

engine = create_engine(
    settings.sqlalchemy_database_url,
    connect_args=_connect_args,
    # Cheap health-check before reusing a pooled connection — hosted
    # Postgres (Neon's free tier suspends idle compute) can otherwise hand
    # back a stale/closed connection after a period of inactivity.
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class for all ORM models."""


def init_db() -> None:
    """Ensure the data directory exists and create tables if missing.

    Table creation here is a pragmatic MVP approach; Alembic migrations
    (see /alembic) are the source of truth going forward for schema changes.
    """
    if settings.sqlite_path is not None:
        settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    # Import models so they are registered on Base.metadata before create_all.
    from backend.app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a DB session and closes it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
