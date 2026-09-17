"""Pydantic schemas for Marketplace API I/O."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class MarketplaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    country: str
    active: bool
