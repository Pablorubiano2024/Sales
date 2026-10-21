"""Daily sync: keeps every active MercadoLibre listing honest against its
real source.

For each MarketplaceProduct currently ACTIVE on MercadoLibre:
  1. Re-fetch the product live from its ORIGIN source — the one its SKU
     was built from (listing_optimizer.origin_source). Not the other
     sources discovery attached to the same product: checked 2026-10-15,
     those are often a different item. Before that date this picked an
     arbitrary one of them, while the optimizer priced from another.
  2. Recompute its opportunity from the live price via the same
     buy/sell/fee math discovery uses (build_opportunity_inputs), which
     also reclassifies it (approved/promising/rejected/review).
  3. If it's gone, out of stock or fell below "promising" -> pause the
     listing (reversible).
  4. Price is NOT set here — scripts/optimize_listings.py runs right
     after this in the same workflow and owns pricing (see
     backend/app/services/listing_optimizer.py).

PAUSED listings get steps 1 and 2 too (fresh buy price, stock and
classification) so the optimizer, which runs next, can reactivate the
ones that are profitable again under its ROI gate. Before 2026-10-15
pausing was one-way; that left a one-off source fetch failure (Quick
3.5L, the 2nd most-visited listing) and listings whose buy price later
dropped (Digital 8L: 359,900 -> 199,900) off for good.

Meant to run once a day via a scheduler (see .github/workflows/ for the
GitHub Actions cron wiring this into).

Usage:
    python scripts/sync_marketplace_listings.py
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.config import get_settings  # noqa: E402
from backend.app.core.database import SessionLocal, init_db  # noqa: E402
from backend.app.core.logging import get_logger  # noqa: E402
from backend.app.core.time import utcnow  # noqa: E402
from backend.app.integrations.mercadolibre import MercadoLibreAdapter  # noqa: E402
from backend.app.jobs.discovery import build_opportunity_inputs  # noqa: E402
from backend.app.models.marketplace import ListingStatus, MarketplaceProduct  # noqa: E402
from backend.app.models.opportunity import OpportunityStatus  # noqa: E402
from backend.app.models.source import Source  # noqa: E402
from backend.app.services import listing_draft_service, listing_service  # noqa: E402
from backend.app.services.arbitrage_engine import evaluate_opportunity  # noqa: E402
from backend.app.services.listing_optimizer import origin_source  # noqa: E402

logger = get_logger(__name__)

# Domestic-shipping override — same reasoning as discover_falabella.py:
# CJ-tuned Settings.shipping_cost_cop assumes international freight.
DOMESTIC_SHIPPING_COST_COP = Decimal("15000")

# Source name -> adapter: the same map publishing uses, so every source we
# can publish from is also checked daily (until 2026-10-15 this was a
# separate 4-source copy missing Alkosto, Ktronix and Tecnologia Mayorista).
SUPPORTED_SOURCES = listing_draft_service.SUPPORTED_SOURCES

# Reclassifying below these statuses means the listing is no longer worth
# keeping live.
VIABLE_STATUSES = {OpportunityStatus.APPROVED, OpportunityStatus.PROMISING}


def main() -> None:
    init_db()
    settings = get_settings()
    db = SessionLocal()
    paused = unchanged = skipped = 0
    try:
        # Includes PAUSED, not just ACTIVE: a freshly created item's status
        # can be a transient value (e.g. "paused" pending MercadoLibre's
        # own async review) that resolves to "active" only moments later —
        # confirmed live 2026-09-22. Reconciling every non-closed row's
        # real status first means a listing published just before this
        # runs doesn't sit invisible to the sync job forever; a row that's
        # genuinely paused (by us, or by ML) is refreshed right back to
        # "paused" and then skipped below, same as before.
        candidates = (
            db.query(MarketplaceProduct)
            .filter(MarketplaceProduct.status.in_([ListingStatus.ACTIVE, ListingStatus.PAUSED]))
            .all()
        )
        print(f"{len(candidates)} publicaciones activas/pausadas a revisar.")

        with MercadoLibreAdapter(db) as ml_adapter:
            if not ml_adapter.authenticate():
                sys.exit("No hay una cuenta de MercadoLibre conectada/válida.")

            listings = []
            for candidate in candidates:
                listing_service.refresh_listing_status(db, ml_adapter, candidate)
                if candidate.status in (ListingStatus.ACTIVE, ListingStatus.PAUSED):
                    listings.append(candidate)
            active_count = sum(1 for x in listings if x.status == ListingStatus.ACTIVE)
            print(
                f"{active_count} confirmadas activas y {len(listings) - active_count} "
                "pausadas tras refrescar su estado real."
            )

            for listing in listings:
                is_active = listing.status == ListingStatus.ACTIVE
                product = listing.product
                label = f"[{product.sku}] {product.name[:60]}"

                opportunity, source_product = origin_source(db, listing)
                source = db.get(Source, opportunity.source_id) if opportunity else None
                adapter_cls = SUPPORTED_SOURCES.get(source.name if source else "")
                if opportunity is None or source_product is None or adapter_cls is None:
                    print(f"SKIP  {label}: fuente de origen no soportada / sin Opportunity")
                    skipped += 1
                    continue
                assert source_product.external_id is not None

                with adapter_cls() as source_adapter:
                    live = source_adapter.get_product(source_product.external_id)

                reason = None
                if live is None:
                    # Gone, or a one-off fetch failure: unavailable as of this
                    # check (the optimizer won't reactivate on an older read);
                    # the next successful check restores it.
                    source_product.stock_available = False
                    source_product.last_checked_at = utcnow()
                    db.commit()
                    reason = "fuente de origen no respondió / producto no disponible"
                else:
                    source_product.current_price = live.price
                    source_product.stock_available = live.stock_available
                    source_product.last_checked_at = utcnow()
                    db.commit()
                    inputs = build_opportunity_inputs(
                        live,
                        product.id,
                        opportunity.source_id,
                        listing.marketplace_id,
                        settings,
                        shipping_cost_cop=DOMESTIC_SHIPPING_COST_COP,
                        min_buy_price_cop=Decimal("0"),
                    )
                    pictures = live.image_urls[: listing_draft_service.MAX_PICTURES]
                    if listing_service.repair_stuck_pictures(ml_adapter, listing, pictures):
                        print(f"FOTOS    {label}: reenviadas {len(pictures)} fotos de la fuente")
                    if not live.stock_available:
                        reason = "fuente de origen sin stock"
                    elif inputs is None:
                        reason = "precio de compra por debajo del mínimo"
                    else:
                        opportunity = evaluate_opportunity(db, inputs)
                        if opportunity.status not in VIABLE_STATUSES:
                            reason = f"reclasificada como '{opportunity.status.value}'"

                if reason and is_active:
                    listing_service.pause_listing(db, ml_adapter, listing, reason=reason)
                    print(f"PAUSADA  {label}: {reason}")
                    paused += 1
                    continue

                # Price is owned by scripts/optimize_listings.py (runs right
                # after this in the same workflow) — it prices from the
                # cheapest fresh, in-stock source refreshed just above, never
                # below the ROI floor. Pushing the estimated sell price here
                # would undo that every day.
                unchanged += 1

        print(f"\nPausadas: {paused}  Sin cambios: {unchanged}  Omitidas: {skipped}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
