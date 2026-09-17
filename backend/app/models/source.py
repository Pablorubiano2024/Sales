"""Source domain models: where a product can be purchased, and the
per-source listing of a canonical Product (price, stock, URL, etc.)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base
from backend.app.core.time import utcnow

if TYPE_CHECKING:
    from backend.app.models.product import Product


def _uuid() -> str:
    return str(uuid.uuid4())


class SourceType(str, enum.Enum):
    """Kind of supplier/source integration."""

    MOCK = "mock"
    API = "api"
    SCRAPER = "scraper"
    MARKETPLACE = "marketplace"
    MANUAL = "manual"


class Source(Base):
    """A supplier / retailer / marketplace where products can be bought."""

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128))
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType), default=SourceType.MOCK)
    base_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    country: Mapped[str] = mapped_column(String(2), default="CO")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    source_products: Mapped[list[SourceProduct]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Source {self.name} ({self.source_type.value})>"


class SourceProduct(Base):
    """A canonical Product as it exists at a particular Source."""

    __tablename__ = "source_products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)

    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    current_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="COP")
    stock_available: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    source: Mapped[Source] = relationship(back_populates="source_products")
    product: Mapped[Product] = relationship(back_populates="source_products")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<SourceProduct product={self.product_id} "
            f"source={self.source_id} price={self.current_price}>"
        )
