"""A reviewable publish draft — distinct from `MarketplaceProduct`, which
means "this is actually live on MercadoLibre". A draft is generated from
real product/opportunity data (never fabricated), reviewed by the user in
Streamlit, and only becomes a real listing once approved and explicitly
published (still a separate, deliberate action — see
listing_service.publish_and_record).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base
from backend.app.core.time import utcnow

if TYPE_CHECKING:
    from backend.app.models.opportunity import Opportunity


def _uuid() -> str:
    return str(uuid.uuid4())


class ListingDraftStatus(str, enum.Enum):
    DRAFT = "draft"
    READY = "ready"
    PUBLISHED = "published"
    REJECTED = "rejected"


class ListingDraft(Base):
    __tablename__ = "listing_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)

    title: Mapped[str] = mapped_column(String(60))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON-encoded list[str] — same "Text holding real JSON" convention
    # Opportunity.ai_analysis already uses, kept consistent rather than
    # introducing a JSON column type only some tables use.
    bullets: Mapped[str | None] = mapped_column(Text, nullable=True)
    attributes: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_urls: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))

    status: Mapped[ListingDraftStatus] = mapped_column(
        Enum(ListingDraftStatus), default=ListingDraftStatus.DRAFT, index=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    opportunity: Mapped[Opportunity] = relationship()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ListingDraft opportunity={self.opportunity_id} status={self.status.value}>"
