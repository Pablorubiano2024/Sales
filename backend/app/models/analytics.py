"""One row per measurable real event in an opportunity's life — the
source of truth the Confidence Engine recalibrates against later
(estimated vs. real margin, whether something detected ever sold). Never
holds a derived/computed metric that isn't traceable to a real event.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base
from backend.app.core.time import utcnow

if TYPE_CHECKING:
    from backend.app.models.opportunity import Opportunity


def _uuid() -> str:
    return str(uuid.uuid4())


class AnalyticsEventType(str, enum.Enum):
    DETECTED = "detected"
    PUBLISHED = "published"
    SOLD = "sold"
    EXPIRED = "expired"


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)
    event_type: Mapped[AnalyticsEventType] = mapped_column(Enum(AnalyticsEventType), index=True)

    # Real, denormalized at event time (not re-derived later) so the
    # historical record doesn't silently change if the Opportunity is
    # recomputed afterward.
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    estimated_margin: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    real_margin: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    time_to_sale_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence_score_at_detection: Mapped[int | None] = mapped_column(Integer, nullable=True)

    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    opportunity: Mapped[Opportunity] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AnalyticsEvent opportunity={self.opportunity_id} type={self.event_type.value}>"
