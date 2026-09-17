"""Pydantic schemas for Order API I/O."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from backend.app.models.order import CustomerShippingStatus, OrderStatus


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    marketplace_order_id: str | None
    product_id: str
    opportunity_id: str | None

    selling_price: float
    supplier_price: float
    marketplace_fees: float
    shipping_cost: float
    other_costs: float
    expected_profit: float

    status: OrderStatus
    customer_shipping_status: CustomerShippingStatus

    created_at: datetime
    updated_at: datetime
