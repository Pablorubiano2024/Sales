"""Order domain model.

Represents a marketplace sale that must be fulfilled by manually (for now)
purchasing from the supplier and having it drop-shipped to the customer.
No inventory is held. Sensitive customer PII is intentionally NOT stored
here in the MVP.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base
from backend.app.core.time import utcnow

if TYPE_CHECKING:
    from backend.app.models.product import Product


def _uuid() -> str:
    return str(uuid.uuid4())


class OrderStatus(str, enum.Enum):
    """Business/fulfillment status of the arbitrage order itself."""

    NEW = "new"
    AWAITING_SUPPLIER_PURCHASE = "awaiting_supplier_purchase"
    PURCHASED_FROM_SUPPLIER = "purchased_from_supplier"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class CustomerShippingStatus(str, enum.Enum):
    """Status of the shipment to the end customer (supplier -> customer)."""

    NOT_SHIPPED = "not_shipped"
    SHIPPED = "shipped"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    RETURNED = "returned"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    marketplace_order_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), index=True)
    opportunity_id: Mapped[str | None] = mapped_column(
        ForeignKey("opportunities.id"), nullable=True
    )

    selling_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    supplier_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    marketplace_fees: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    shipping_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    other_costs: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    expected_profit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)

    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus), default=OrderStatus.NEW, index=True
    )
    customer_shipping_status: Mapped[CustomerShippingStatus] = mapped_column(
        Enum(CustomerShippingStatus), default=CustomerShippingStatus.NOT_SHIPPED
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    product: Mapped[Product] = relationship(back_populates="orders")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Order product={self.product_id} status={self.status.value}>"
