"""Market Gap Scanner (Autopilot Phase 4) — captures a real Buy Box
snapshot per tracked Opportunity and raises a MarketGapEvent when
something real changed since the last snapshot. Read-only against
MercadoLibre — never publishes or modifies anything there.

Feeds Phase 1 (opportunity_validator's seller_count check) and Phase 2
(confidence_engine's competition factor) real data instead of their
proxies — both already read the latest MarketGapSnapshot for an
Opportunity, so simply running this populates real data for them with no
further changes needed there.

Like discovery.py/price_monitor.py, this is invoked manually / from a
script for now; a scheduler can call `run_market_gap_scan` directly once
one exists (Phase 7).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from backend.app.core.logging import get_logger
from backend.app.models.market_gap import MarketGapEvent, MarketGapEventType, MarketGapSnapshot
from backend.app.models.opportunity import Opportunity
from backend.app.services.catalog_lookup import find_catalog_product, get_buy_box_snapshot

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ScanResult:
    scanned: int = 0
    skipped_no_catalog_match: int = 0
    events_detected: int = 0


def _latest_snapshot(db: Session, opportunity_id: str) -> MarketGapSnapshot | None:
    return (
        db.query(MarketGapSnapshot)
        .filter_by(opportunity_id=opportunity_id)
        .order_by(MarketGapSnapshot.captured_at.desc())
        .first()
    )


def _resolve_catalog_product_id(
    db: Session, opportunity: Opportunity, *, client: httpx.Client, access_token: str
) -> str | None:
    """Reuse the catalog_product_id from this Opportunity's last snapshot
    when we have one (avoids re-searching the catalog every scan);
    otherwise search once via the real product name."""
    previous = _latest_snapshot(db, opportunity.id)
    if previous is not None:
        return previous.catalog_product_id
    product_name = opportunity.product.name if opportunity.product else None
    if not product_name:
        return None
    return find_catalog_product(product_name, client=client, access_token=access_token)


def _detect_events(
    previous: MarketGapSnapshot | None, current: MarketGapSnapshot
) -> list[tuple[MarketGapEventType, str]]:
    """Only ever compares two REAL snapshots — nothing here is inferred
    without both a before and an after."""
    if previous is None:
        return []
    events: list[tuple[MarketGapEventType, str]] = []

    if (
        previous.buy_box_seller_id is not None
        and current.buy_box_seller_id != previous.buy_box_seller_id
    ):
        events.append(
            (
                MarketGapEventType.LOWEST_SELLER_DISAPPEARED,
                f"Vendedor ganador cambió: {previous.buy_box_seller_id} -> "
                f"{current.buy_box_seller_id or 'ninguno'}",
            )
        )
    if (
        previous.buy_box_price is not None
        and current.buy_box_price is not None
        and current.buy_box_price > previous.buy_box_price
    ):
        events.append(
            (
                MarketGapEventType.BUY_BOX_PRICE_INCREASED,
                f"Precio ganador subió: {previous.buy_box_price} -> {current.buy_box_price}",
            )
        )
    if current.seller_count < previous.seller_count:
        events.append(
            (
                MarketGapEventType.SELLER_COUNT_DROPPED,
                f"Vendedores activos: {previous.seller_count} -> {current.seller_count}",
            )
        )
    if not previous.stock_available and current.stock_available:
        events.append(
            (
                MarketGapEventType.STOCK_RECOVERED,
                "Volvió a haber vendedores activos tras no haber ninguno",
            )
        )
    return events


def run_market_gap_scan(
    db: Session, opportunities: list[Opportunity], *, client: httpx.Client, access_token: str
) -> ScanResult:
    """Scan the given Opportunities (caller decides which — e.g. APPROVED/
    PROMISING only, to respect MercadoLibre's real rate limits rather than
    scanning everything ever discovered)."""
    scanned = skipped = events_detected = 0
    for opportunity in opportunities:
        catalog_product_id = _resolve_catalog_product_id(
            db, opportunity, client=client, access_token=access_token
        )
        if catalog_product_id is None:
            skipped += 1
            logger.info(
                "Market gap scan: sin match de catálogo real para oportunidad %s (%s)",
                opportunity.id,
                opportunity.product.name if opportunity.product else "?",
            )
            continue

        buy_box = get_buy_box_snapshot(catalog_product_id, client=client, access_token=access_token)
        if buy_box is None:
            skipped += 1
            continue

        previous = _latest_snapshot(db, opportunity.id)
        current = MarketGapSnapshot(
            catalog_product_id=catalog_product_id,
            opportunity_id=opportunity.id,
            seller_count=buy_box.seller_count,
            buy_box_price=buy_box.buy_box_price,
            buy_box_seller_id=buy_box.buy_box_seller_id,
            stock_available=buy_box.stock_available,
        )
        db.add(current)
        db.commit()
        db.refresh(current)
        scanned += 1

        for event_type, detail in _detect_events(previous, current):
            db.add(
                MarketGapEvent(
                    catalog_product_id=catalog_product_id,
                    opportunity_id=opportunity.id,
                    event_type=event_type,
                    previous_snapshot_id=previous.id if previous else None,
                    current_snapshot_id=current.id,
                    detail=detail,
                )
            )
            events_detected += 1
            logger.info(
                "Market gap event %s for opportunity %s: %s",
                event_type.value,
                opportunity.id,
                detail,
            )
        db.commit()

    return ScanResult(
        scanned=scanned, skipped_no_catalog_match=skipped, events_detected=events_detected
    )
