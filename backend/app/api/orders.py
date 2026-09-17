"""Order API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.security import require_api_key
from backend.app.models.order import Order, OrderStatus
from backend.app.schemas.order import OrderRead

router = APIRouter(prefix="/api/orders", tags=["orders"], dependencies=[Depends(require_api_key)])


@router.get("", response_model=list[OrderRead])
def list_orders(
    status_filter: OrderStatus | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[Order]:
    query = db.query(Order)
    if status_filter is not None:
        query = query.filter(Order.status == status_filter)
    return query.order_by(Order.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/{order_id}", response_model=OrderRead)
def get_order(order_id: str, db: Session = Depends(get_db)) -> Order:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order
