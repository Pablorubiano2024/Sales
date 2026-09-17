"""Tiny time helper so models don't rely on the deprecated `datetime.utcnow`."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Naive UTC datetime (matches the non-timezone-aware `DateTime` columns)."""
    return datetime.now(UTC).replace(tzinfo=None)
