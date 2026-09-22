"""Stored OAuth credentials for a marketplace integration (e.g. MercadoLibre).

Separate table rather than columns on `Marketplace` because these are
sensitive, single-purpose, and only exist once real OAuth is wired up —
most marketplaces in this table will never have a credential row.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base
from backend.app.core.time import utcnow

if TYPE_CHECKING:
    from backend.app.models.marketplace import Marketplace


def _uuid() -> str:
    return str(uuid.uuid4())


class MarketplaceCredential(Base):
    """OAuth tokens for one marketplace. One row per marketplace (the
    `marketplace_id` unique constraint enforces that) — this platform only
    ever operates as a single seller account per marketplace, not a
    multi-tenant integration."""

    __tablename__ = "marketplace_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    marketplace_id: Mapped[str] = mapped_column(
        ForeignKey("marketplaces.id"), unique=True, index=True
    )

    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str] = mapped_column(Text)
    token_type: Mapped[str] = mapped_column(String(32), default="bearer")
    scope: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # The remote account this credential authenticates as (MercadoLibre's
    # `user_id` from the token response) — useful to confirm we connected
    # the account we meant to.
    external_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    marketplace: Mapped[Marketplace] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<MarketplaceCredential marketplace={self.marketplace_id} "
            f"user={self.external_user_id}>"
        )
