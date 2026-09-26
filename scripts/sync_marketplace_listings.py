"""Daily sync: keeps every active MercadoLibre listing honest against its
real source.

For each MarketplaceProduct currently ACTIVE on MercadoLibre:
  1. Re-fetch the product live from its source (Falabella today).
  2. If it's gone / out of stock -> pause the listing (reversible — see
     the user's confirmed choice over permanently closing it).
  3. Otherwise recompute the opportunity from the live price via the same
     buy/sell/fee math discovery uses (build_opportunity_inputs), which
     also reclassifies it (approved/promising/rejected/review).
  4. If it fell below "promising" -> pause the listing.
  5. Else if the real sell price moved -> push the new price to
     MercadoLibre (update_listing_price).

Intentionally does NOT reactivate a paused listing — pausing here is a
one-way signal ("something needs a human look"); re-publishing is a
deliberate act (scripts/publish_approved_opportunities.py), not something
this job should undo on its own.

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
from backend.app.integrations.base import SourceAdapter  # noqa: E402
from backend.app.integrations.falabella_source import (  # noqa: E402
    FalabellaSourceAdapter,
    HomecenterSourceAdapter,
)
from backend.app.integrations.imusa_source import (  # noqa: E402
    ImusaSourceAdapter,
    JumboSourceAdapter,
)
from backend.app.integrations.mercadolibre import MercadoLibreAdapter  # noqa: E402
from backend.app.jobs.discovery import build_opportunity_inputs  # noqa: E402
from backend.app.models.marketplace import ListingStatus, MarketplaceProduct  # noqa: E402
from backend.app.models.opportunity import Opportunity, OpportunityStatus  # noqa: E402
from backend.app.models.source import Source, SourceProduct  # noqa: E402
from backend.app.services import listing_service  # noqa: E402
from backend.app.services.arbitrage_engine import evaluate_opportunity  # noqa: E402

logger = get_logger(__name__)

# Domestic-shipping override — same reasoning as discover_falabella.py:
# CJ-tuned Settings.shipping_cost_cop assumes international freight.
DOMESTIC_SHIPPING_COST_COP = Decimal("15000")

# Source name -> adapter factory, mirrors publish_approved_opportunities.py.
SUPPORTED_SOURCES: dict[str, type[SourceAdapter]] = {
    "Falabella Colombia": FalabellaSourceAdapter,
    "Homecenter Colombia": HomecenterSourceAdapter,
    "Imusa Colombia": ImusaSourceAdapter,
    "Jumbo Colombia": JumboSourceAdapter,
}

# Reclassifying below these statuses means the listing is no longer worth
# keeping live.
VIABLE_STATUSES = {OpportunityStatus.APPROVED, OpportunityStatus.PROMISING}


def main() -> None:
    init_db()
    settings = get_settings()
    db = SessionLocal()
    paused = updated = unchanged = skipped = 0
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
                if candidate.status == ListingStatus.ACTIVE:
                    listings.append(candidate)
            print(f"{len(listings)} confirmadas activas tras refrescar su estado real.")

            for listing in listings:
                product = listing.product
                label = f"[{product.sku}] {product.name[:60]}"

                opportunity = (
                    db.query(Opportunity)
                    .filter_by(product_id=product.id, marketplace_id=listing.marketplace_id)
                    .first()
                )
                if opportunity is None:
                    print(f"SKIP  {label}: sin Opportunity asociada")
                    skipped += 1
                    continue

                source = db.get(Source, opportunity.source_id)
                adapter_cls = SUPPORTED_SOURCES.get(source.name if source else "")
                if adapter_cls is None:
                    print(f"SKIP  {label}: fuente '{source.name if source else '?'}' no soportada")
                    skipped += 1
                    continue

                source_product = (
                    db.query(SourceProduct)
                    .filter_by(source_id=opportunity.source_id, product_id=product.id)
                    .first()
                )
                if source_product is None or not source_product.external_id:
                    print(f"SKIP  {label}: sin SourceProduct.external_id")
                    skipped += 1
                    continue

                with adapter_cls() as source_adapter:
                    live = source_adapter.get_product(source_product.external_id)

                if live is None or not live.stock_available:
                    listing_service.pause_listing(
                        db, ml_adapter, listing, reason="fuente sin stock / producto no disponible"
                    )
                    print(f"PAUSADA  {label}: ya no disponible en la fuente")
                    paused += 1
                    continue

                source_product.current_price = live.price
                source_product.stock_available = live.stock_available
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
                if inputs is None:
                    listing_service.pause_listing(
                        db, ml_adapter, listing, reason="precio de compra por debajo del mínimo"
                    )
                    print(f"PAUSADA  {label}: precio de compra por debajo del mínimo")
                    paused += 1
                    continue

                opportunity = evaluate_opportunity(db, inputs)

                if opportunity.status not in VIABLE_STATUSES:
                    listing_service.pause_listing(
                        db,
                        ml_adapter,
                        listing,
                        reason=f"reclasificada como '{opportunity.status.value}'",
                    )
                    print(f"PAUSADA  {label}: reclasificada como '{opportunity.status.value}'")
                    paused += 1
                    continue

                new_price = opportunity.sell_price
                if new_price != listing.selling_price:
                    old_price = listing.selling_price
                    listing_service.update_listing_price(db, ml_adapter, listing, new_price)
                    print(f"PRECIO   {label}: {old_price} -> {new_price} COP")
                    updated += 1
                else:
                    unchanged += 1

        print(
            f"\nPausadas: {paused}  Precio actualizado: {updated}  "
            f"Sin cambios: {unchanged}  Omitidas: {skipped}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
