"""Opportunity domain model: a calculated arbitrage opportunity for a
product between a Source (buy side) and a Marketplace (sell side)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base
from backend.app.core.time import utcnow

if TYPE_CHECKING:
    from backend.app.models.product import Product


def _uuid() -> str:
    return str(uuid.uuid4())


class OpportunityStatus(str, enum.Enum):
    """Classification produced by the (deterministic) opportunity engine."""

    REJECTED = "rejected"
    REVIEW = "review"
    PROMISING = "promising"
    APPROVED = "approved"


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"), index=True)
    marketplace_id: Mapped[str] = mapped_column(ForeignKey("marketplaces.id"), index=True)

    # --- Inputs ---
    buy_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    sell_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    marketplace_fee: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    shipping_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    tax_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    payment_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    other_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)

    # --- Deterministic outputs (from pricing_engine) ---
    gross_profit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    net_profit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    roi: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0)
    margin: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=0)

    # --- Scoring (AI-enriched; not the source of truth for financials) ---
    competition_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    demand_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    ai_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)

    status: Mapped[OpportunityStatus] = mapped_column(
        Enum(OpportunityStatus), default=OpportunityStatus.REVIEW, index=True
    )
    ai_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    product: Mapped[Product] = relationship(back_populates="opportunities")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Opportunity product={self.product_id} status={self.status.value} roi={self.roi}>"
