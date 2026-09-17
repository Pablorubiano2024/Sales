"""Marketplace domain models: selling channels and listings."""

from __future__ import annotations

import enum
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base

if TYPE_CHECKING:
    from backend.app.models.product import Product


def _uuid() -> str:
    return str(uuid.uuid4())


class ListingStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


class Marketplace(Base):
    """A selling channel, e.g. MercadoLibre."""

    __tablename__ = "marketplaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128))
    country: Mapped[str] = mapped_column(String(2), default="CO")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    marketplace_products: Mapped[list[MarketplaceProduct]] = relationship(
        back_populates="marketplace", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Marketplace {self.name}>"


class MarketplaceProduct(Base):
    """A canonical Product as listed on a particular Marketplace."""

    __tablename__ = "marketplace_products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    marketplace_id: Mapped[str] = mapped_column(ForeignKey("marketplaces.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)

    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    selling_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="COP")
    status: Mapped[ListingStatus] = mapped_column(Enum(ListingStatus), default=ListingStatus.DRAFT)

    marketplace: Mapped[Marketplace] = relationship(back_populates="marketplace_products")
    product: Mapped[Product] = relationship(back_populates="marketplace_products")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MarketplaceProduct product={self.product_id} marketplace={self.marketplace_id}>"
