"""Opportunity lifecycle tracking — a separate dimension from
`Opportunity.status` (which answers "is this profitable?"). This answers
"where is it in the funnel?" (found -> validated -> published -> sold /
expired / cancelled), independent of whether it's currently profitable.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base
from backend.app.core.time import utcnow

if TYPE_CHECKING:
    from backend.app.models.opportunity import Opportunity


def _uuid() -> str:
    return str(uuid.uuid4())


class LifecycleStage(str, enum.Enum):
    FOUND = "found"
    VALIDATED = "validated"
    PUBLISHED = "published"
    SOLD = "sold"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class OpportunityLifecycleEvent(Base):
    """One transition in an Opportunity's lifecycle, with why it happened."""

    __tablename__ = "opportunity_lifecycle_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)
    stage: Mapped[LifecycleStage] = mapped_column(Enum(LifecycleStage), index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    opportunity: Mapped[Opportunity] = relationship(back_populates="lifecycle_events")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<OpportunityLifecycleEvent opportunity={self.opportunity_id} "
            f"stage={self.stage.value}>"
        )
