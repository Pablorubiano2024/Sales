"""Minimal generic repository helper.

Kept intentionally small for the MVP: most endpoints query SQLAlchemy
models directly through the session. This helper exists for the handful
of "get by id or 404-worthy None" lookups repeated across services/API
routes, and as the natural extension point once real filtering/pagination
needs grow.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy.orm import Session

from backend.app.core.database import Base

ModelType = TypeVar("ModelType", bound=Base)


class Repository(Generic[ModelType]):
    def __init__(self, model: type[ModelType], db: Session) -> None:
        self.model = model
        self.db = db

    def get(self, id_: str) -> ModelType | None:
        return self.db.get(self.model, id_)

    def list(self, limit: int = 100, offset: int = 0) -> list[ModelType]:
        return list(self.db.query(self.model).offset(offset).limit(limit).all())

    def add(self, instance: ModelType) -> ModelType:
        self.db.add(instance)
        self.db.commit()
        self.db.refresh(instance)
        return instance
