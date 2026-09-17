"""Order service.

Encapsulates the "sale detected -> alert user -> user buys from supplier ->
supplier ships to customer" workflow. No inventory is held; purchasing from
the supplier remains a manual step for the MVP (see PROJECT_CONTEXT.md).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.core.logging import get_logger
from backend.app.models.opportunity import Opportunity
from backend.app.models.order import CustomerShippingStatus, Order, OrderStatus
from backend.app.services.pricing_engine import calculate_net_profit

logger = get_logger(__name__)


def create_order_from_opportunity(
    db: Session,
    opportunity: Opportunity,
    marketplace_order_id: str | None = None,
) -> Order:
    """Create an Order when a marketplace sale is detected for a given
    Opportunity. Status starts as NEW / AWAITING_SUPPLIER_PURCHASE so the
    user is prompted to manually buy from the supplier."""
    expected_profit = calculate_net_profit(
        sell_price=opportunity.sell_price,
        buy_price=opportunity.buy_price,
        marketplace_fee=opportunity.marketplace_fee,
        shipping_cost=opportunity.shipping_cost,
        tax_cost=opportunity.tax_cost,
        payment_cost=opportunity.payment_cost,
        other_cost=opportunity.other_cost,
    )

    order = Order(
        marketplace_order_id=marketplace_order_id,
        product_id=opportunity.product_id,
        opportunity_id=opportunity.id,
        selling_price=opportunity.sell_price,
        supplier_price=opportunity.buy_price,
        marketplace_fees=opportunity.marketplace_fee,
        shipping_cost=opportunity.shipping_cost,
        other_costs=opportunity.tax_cost + opportunity.payment_cost + opportunity.other_cost,
        expected_profit=expected_profit,
        status=OrderStatus.AWAITING_SUPPLIER_PURCHASE,
        customer_shipping_status=CustomerShippingStatus.NOT_SHIPPED,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    logger.info(
        "Order created for opportunity %s: expected_profit=%s — ALERT: manually "
        "purchase from supplier and ship to customer.",
        opportunity.id,
        expected_profit,
    )
    return order


def mark_purchased_from_supplier(db: Session, order: Order) -> Order:
    order.status = OrderStatus.PURCHASED_FROM_SUPPLIER
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def mark_shipped(db: Session, order: Order) -> Order:
    order.customer_shipping_status = CustomerShippingStatus.SHIPPED
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def mark_completed(db: Session, order: Order) -> Order:
    order.status = OrderStatus.COMPLETED
    order.customer_shipping_status = CustomerShippingStatus.DELIVERED
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def cancel_order(db: Session, order: Order) -> Order:
    order.status = OrderStatus.CANCELLED
    db.add(order)
    db.commit()
    db.refresh(order)
    return order
