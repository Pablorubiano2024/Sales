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

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

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
