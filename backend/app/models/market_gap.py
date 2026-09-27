"""Market Gap Scanner models — MercadoLibre's real Buy Box data only exists
for catalog-listing items (`GET /products/{catalog_product_id}` ->
`buy_box_winner`; `GET /products/{id}/items` for the competing sellers),
verified live 2026-09-26. `MarketGapSnapshot` stores one real reading per
scan; `MarketGapEvent` is only written when a scan's snapshot actually
differs from the immediately-previous one for that catalog_product_id —
never one row per scan regardless of change.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import utcnow


def _uuid() -> str:
    return str(uuid.uuid4())


class MarketGapEventType(str, enum.Enum):
    LOWEST_SELLER_DISAPPEARED = "lowest_seller_disappeared"
    BUY_BOX_PRICE_INCREASED = "buy_box_price_increased"
    SELLER_COUNT_DROPPED = "seller_count_dropped"
    STOCK_RECOVERED = "stock_recovered"


class MarketGapSnapshot(Base):
    """One real Buy Box reading for a catalog_product_id at a point in time."""

    __tablename__ = "market_gap_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    catalog_product_id: Mapped[str] = mapped_column(String(64), index=True)
    opportunity_id: Mapped[str | None] = mapped_column(
        ForeignKey("opportunities.id"), nullable=True, index=True
    )
    seller_count: Mapped[int] = mapped_column(Integer)
    buy_box_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    buy_box_seller_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stock_available: Mapped[bool] = mapped_column(default=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<MarketGapSnapshot catalog_product_id={self.catalog_product_id} "
            f"sellers={self.seller_count}>"
        )


class MarketGapEvent(Base):
    """A real, detected change between two consecutive snapshots for the
    same catalog_product_id — never fabricated, always diffed from real
    Buy Box data."""

    __tablename__ = "market_gap_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    catalog_product_id: Mapped[str] = mapped_column(String(64), index=True)
    opportunity_id: Mapped[str | None] = mapped_column(
        ForeignKey("opportunities.id"), nullable=True, index=True
    )
    event_type: Mapped[MarketGapEventType] = mapped_column(Enum(MarketGapEventType), index=True)
    previous_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("market_gap_snapshots.id"), nullable=True
    )
    current_snapshot_id: Mapped[str] = mapped_column(ForeignKey("market_gap_snapshots.id"))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<MarketGapEvent catalog_product_id={self.catalog_product_id} "
            f"type={self.event_type.value}>"
        )
