"""Product API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.security import require_api_key
from backend.app.models.product import Product
from backend.app.schemas.product import ProductCreate, ProductRead

router = APIRouter(
    prefix="/api/products", tags=["products"], dependencies=[Depends(require_api_key)]
)


@router.get("", response_model=list[ProductRead])
def list_products(
    active: bool | None = None,
    category: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[Product]:
    query = db.query(Product)
    if active is not None:
        query = query.filter(Product.active == active)
    if category is not None:
        query = query.filter(Product.category == category)
    return query.offset(offset).limit(limit).all()


@router.get("/{product_id}", response_model=ProductRead)
def get_product(product_id: str, db: Session = Depends(get_db)) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return product


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)) -> Product:
    product = Product(**payload.model_dump())
    db.add(product)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Product with this SKU already exists"
        ) from exc
    db.refresh(product)
    return product
