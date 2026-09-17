"""SQLAlchemy engine/session setup.

Uses SQLite for the MVP. The engine is built from `DATABASE_URL` so
switching to PostgreSQL later only requires changing that one setting
(plus, if needed, adding `psycopg` as a dependency).
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.app.core.config import get_settings

settings = get_settings()

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=_connect_args)
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
