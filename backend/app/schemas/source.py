"""Pydantic schemas for Source API I/O."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from backend.app.models.source import SourceType


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    source_type: SourceType
    country: str
    active: bool
