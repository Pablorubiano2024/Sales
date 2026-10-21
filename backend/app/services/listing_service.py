"""Connects a real MercadoLibre listing to a persisted `MarketplaceProduct`
row, so a later job (scripts/sync_marketplace_listings.py) knows which
Product/Opportunity a given real `external_id` belongs to — without this,
create_listing()'s result was thrown away the moment the script exited.

Typed against `MercadoLibreAdapter` specifically, not the abstract
`MarketplaceAdapter` — `create_listing`'s real required extras
(category_id, brand, model, ...) aren't part of the generic interface
(see mercadolibre.py's docstring for why), and this module has no other
real adapter to be generic over yet.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.logging import get_logger
from backend.app.integrations.mercadolibre import MercadoLibreAdapter
from backend.app.models.marketplace import ListingStatus, MarketplaceProduct

logger = get_logger(__name__)


def get_listing(db: Session, product_id: str, marketplace_id: str) -> MarketplaceProduct | None:
    return (
        db.query(MarketplaceProduct)
        .filter_by(product_id=product_id, marketplace_id=marketplace_id)
        .first()
    )


def _to_listing_status(raw: str) -> ListingStatus:
    try:
        return ListingStatus(raw)
    except ValueError:
        logger.warning("Unrecognized MercadoLibre item status %r; storing as 'active'", raw)
        return ListingStatus.ACTIVE


def publish_and_record(
    db: Session,
    adapter: MercadoLibreAdapter,
    product_id: str,
    marketplace_id: str,
    title: str,
    price: Decimal,
    currency: str,
    **create_listing_kwargs: Any,
) -> MarketplaceProduct:
    """Publish via `create_listing`, then upsert the `MarketplaceProduct`
    row tracking it (one per product+marketplace — republishing updates
    the existing row rather than creating a duplicate)."""
    listing = adapter.create_listing(product_id, title, price, currency, **create_listing_kwargs)

    record = get_listing(db, product_id, marketplace_id)
    if record is None:
        record = MarketplaceProduct(product_id=product_id, marketplace_id=marketplace_id)
        db.add(record)

    record.external_id = listing.external_id
    record.url = listing.url
    record.selling_price = listing.price
    record.currency = listing.currency
    record.status = _to_listing_status(listing.status)
    db.commit()
    db.refresh(record)
    logger.info(
        "Recorded MarketplaceProduct for product=%s -> ML item=%s", product_id, listing.external_id
    )
    return record


def refresh_listing_status(
    db: Session, adapter: MercadoLibreAdapter, record: MarketplaceProduct
) -> MarketplaceProduct:
    """Re-fetch the item's real current status from MercadoLibre and
    persist it. A freshly created item's status can be a transient value
    (e.g. "paused" pending an async review) that resolves moments later —
    confirmed live 2026-09-22, publishing 7 real items: the create
    response reported "paused" for every one, but re-checking minutes
    later showed a mix of active/under_review/genuinely-paused. Anything
    that depends on the *current* state (the daily sync job only looks at
    ACTIVE rows) must call this rather than trust create_listing's
    snapshot forever."""
    if record.external_id is None:
        return record
    listing = adapter.get_listing(record.external_id)
    if listing is not None:
        record.status = _to_listing_status(listing.status)
        db.commit()
        db.refresh(record)
    return record


STUCK_PICTURES_SUB_STATUS = {"picture_download_pending", "waiting_for_patch"}


def repair_stuck_pictures(
    adapter: MercadoLibreAdapter, record: MarketplaceProduct, image_urls: Sequence[str]
) -> bool:
    """MercadoLibre keeps an item `under_review` with sub_status
    picture_download_pending + waiting_for_patch when it couldn't use a
    photo — it waits for the seller to send new ones (2026-10-21: 6 items
    published with Alkosto's SVG logo as their only photo, one stuck for 6
    days). Re-sends the source's current photos; True if it did."""
    if record.external_id is None or not image_urls:
        return False
    listing = adapter.get_listing(record.external_id)
    sub_status = set((listing.raw or {}).get("sub_status") or []) if listing else set()
    if not STUCK_PICTURES_SUB_STATUS <= sub_status:
        return False
    adapter.update_listing(record.external_id, pictures=[{"source": u} for u in image_urls])
    return True


def pause_listing(
    db: Session, adapter: MercadoLibreAdapter, record: MarketplaceProduct, reason: str
) -> None:
    """No-op if there's nothing real published yet."""
    if record.external_id is None or record.status == ListingStatus.PAUSED:
        return
    adapter.update_listing(record.external_id, status="paused")
    record.status = ListingStatus.PAUSED
    db.commit()
    logger.info("Paused ML item=%s (product=%s): %s", record.external_id, record.product_id, reason)


def activate_listing(db: Session, adapter: MercadoLibreAdapter, record: MarketplaceProduct) -> None:
    """Undo pause_listing. Callers own the decision (listing_optimizer's
    ROI-gated reactivation)."""
    if record.external_id is None:
        return
    adapter.update_listing(record.external_id, status="active")
    record.status = ListingStatus.ACTIVE
    db.commit()
    logger.info("Reactivated ML item=%s (product=%s)", record.external_id, record.product_id)


def update_listing_price(
    db: Session, adapter: MercadoLibreAdapter, record: MarketplaceProduct, new_price: Decimal
) -> None:
    if record.external_id is None:
        return
    adapter.update_price(record.external_id, new_price)
    record.selling_price = new_price
    db.commit()
    logger.info(
        "Updated price for ML item=%s (product=%s) to %s",
        record.external_id,
        record.product_id,
        new_price,
    )
