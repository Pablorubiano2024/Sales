"""Order Router (Autopilot Phase 5) — when a real marketplace sale
happens, creates an internal Order and picks which real supplier to buy
from.

Two modes, per the user's own request:
  - Sandbox (implemented here): fully simulated bookkeeping — never
    touches a supplier's site, just records the Order and the chosen
    SourceProduct.
  - Assisted (Playwright, pre-fills a supplier's real checkout with cart/
    address/quantity but NEVER completes payment or enters card data): NOT
    implemented — deliberately deferred until explicitly re-confirmed with
    the user, given the real risk of automating a third-party site.

"Best supplier" is picked from the real SourceProduct rows already
tracked for a Product. No delivery-time field exists anywhere in this
schema (never invented one for this) — selection is deterministic on what
IS real: in-stock sources only, cheapest current_price among them.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.core.logging import get_logger
from backend.app.core.time import utcnow
from backend.app.models.analytics import AnalyticsEvent, AnalyticsEventType
from backend.app.models.lifecycle import LifecycleStage, OpportunityLifecycleEvent
from backend.app.models.opportunity import Opportunity
from backend.app.models.order import Order, OrderStatus
from backend.app.models.source import Source, SourceProduct
from backend.app.services.pricing_engine import calculate_margin, calculate_net_profit

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SupplierChoice:
    source_product: SourceProduct
    source: Source


def select_best_supplier(db: Session, product_id: str) -> SupplierChoice | None:
    """Cheapest in-stock, real SourceProduct tracked for this Product.
    None when nothing is currently in stock anywhere we track it."""
    candidates = (
        db.query(SourceProduct)
        .filter_by(product_id=product_id, stock_available=True)
        .order_by(SourceProduct.current_price.asc())
        .all()
    )
    if not candidates:
        return None
    chosen = candidates[0]
    return SupplierChoice(source_product=chosen, source=chosen.source)


def _record_sold_analytics(
    db: Session, *, opportunity_id: str, net_profit: Decimal, selling_price: Decimal
) -> None:
    """Real SOLD lifecycle/analytics event — only when the caller actually
    knows which Opportunity this real sale is for (order_sync.py resolves
    this from the sold item's product). time_to_sale is only computed when
    a real FOUND lifecycle event exists for this opportunity — never
    guessed."""
    opportunity = db.get(Opportunity, opportunity_id)
    if opportunity is None:
        return

    real_margin = calculate_margin(net_profit, selling_price)

    found_event = (
        db.query(OpportunityLifecycleEvent)
        .filter_by(opportunity_id=opportunity_id, stage=LifecycleStage.FOUND)
        .order_by(OpportunityLifecycleEvent.occurred_at.asc())
        .first()
    )
    time_to_sale_minutes = None
    if found_event is not None:
        elapsed = utcnow() - found_event.occurred_at
        time_to_sale_minutes = int(elapsed.total_seconds() // 60)

    db.add(
        OpportunityLifecycleEvent(
            opportunity_id=opportunity_id,
            stage=LifecycleStage.SOLD,
            reason="Venta real detectada en MercadoLibre",
        )
    )
    db.add(
        AnalyticsEvent(
            opportunity_id=opportunity_id,
            event_type=AnalyticsEventType.SOLD,
            estimated_margin=opportunity.margin,
            real_margin=real_margin,
            time_to_sale_minutes=time_to_sale_minutes,
            confidence_score_at_detection=opportunity.confidence_score,
        )
    )
    opportunity.lifecycle_stage = LifecycleStage.SOLD
    db.commit()


def create_order_from_sale(
    db: Session,
    *,
    product_id: str,
    selling_price: Decimal,
    marketplace_order_id: str | None = None,
    opportunity_id: str | None = None,
    marketplace_fees: Decimal = Decimal("0"),
    shipping_cost: Decimal = Decimal("0"),
    other_costs: Decimal = Decimal("0"),
) -> Order:
    """Sandbox mode: records a real marketplace sale as an internal Order
    and picks the best real supplier for it — never touches the
    supplier's site. Idempotent on `marketplace_order_id`: a sync/poll job
    that sees the same real sale twice gets the existing Order back
    instead of a duplicate."""
    if marketplace_order_id is not None:
        existing = db.query(Order).filter_by(marketplace_order_id=marketplace_order_id).first()
        if existing is not None:
            return existing

    choice = select_best_supplier(db, product_id)
    supplier_price = choice.source_product.current_price if choice is not None else Decimal("0")

    net_profit = calculate_net_profit(
        selling_price,
        supplier_price,
        marketplace_fees,
        shipping_cost,
        Decimal("0"),
        Decimal("0"),
        other_costs,
    )

    order = Order(
        marketplace_order_id=marketplace_order_id,
        product_id=product_id,
        opportunity_id=opportunity_id,
        selling_price=selling_price,
        supplier_price=supplier_price,
        marketplace_fees=marketplace_fees,
        shipping_cost=shipping_cost,
        other_costs=other_costs,
        expected_profit=net_profit,
        status=OrderStatus.NEW if choice is not None else OrderStatus.AWAITING_SUPPLIER_PURCHASE,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    if opportunity_id is not None:
        _record_sold_analytics(
            db, opportunity_id=opportunity_id, net_profit=net_profit, selling_price=selling_price
        )

    if choice is None:
        logger.warning(
            "Orden %s creada sin proveedor real disponible (sin stock) para producto=%s",
            order.id,
            product_id,
        )
    else:
        logger.info(
            "Orden %s: proveedor elegido=%s precio=%s",
            order.id,
            choice.source.name,
            choice.source_product.current_price,
        )
    return order
