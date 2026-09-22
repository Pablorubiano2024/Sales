"""Publishes every real "approved" Opportunity to MercadoLibre.

Step 1 of the "publicar + sincronizar a diario" plan: this runs BEFORE the
daily sync job takes over the listing's lifecycle
(scripts/sync_marketplace_listings.py — pauses it if the source product
disappears/reclassifies, updates price if it changes).

For each APPROVED opportunity, in order:
  1. Skip if already published (an active/paused MarketplaceProduct row
     for this product+marketplace already exists) — republishing isn't
     needed, the sync job keeps it current.
  2. Re-fetch the product live from its source (currently only Falabella
     has a real adapter) — skip if it went out of stock or disappeared
     since discovery, rather than publish something already invalid.
  3. Predict a category via MercadoLibre's real domain_discovery endpoint
     and confirm the category only requires attributes create_listing()
     already supplies (BRAND, MODEL) — skip anything needing more (e.g.
     POWER_SUPPLY_TYPE), since guessing a per-product value would be
     inventing data. See backend/app/services/category_lookup.py.
  4. Skip if there's no real product photo (MercadoLibre's "free" listing
     type effectively requires one — verified live 2026-09-21).
  5. Publish via listing_service.publish_and_record(), which also records
     the MarketplaceProduct row the sync job depends on.

DRY RUN BY DEFAULT — prints exactly what would happen (publish vs. skip +
reason) without creating any real listing. Real MercadoLibre has no
sandbox: every publish here is a genuine, public, live item a real buyer
could purchase. Pass --confirm to actually publish.

Usage:
    python scripts/publish_approved_opportunities.py            # dry run
    python scripts/publish_approved_opportunities.py --confirm  # for real
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from backend.app.core.database import SessionLocal, init_db  # noqa: E402
from backend.app.core.logging import get_logger  # noqa: E402
from backend.app.integrations.falabella_source import FalabellaSourceAdapter  # noqa: E402
from backend.app.integrations.mercadolibre import MercadoLibreAdapter  # noqa: E402
from backend.app.models.marketplace import ListingStatus, Marketplace  # noqa: E402
from backend.app.models.opportunity import Opportunity, OpportunityStatus  # noqa: E402
from backend.app.models.source import Source, SourceProduct  # noqa: E402
from backend.app.services import category_lookup, listing_service  # noqa: E402

logger = get_logger(__name__)

MAX_TITLE_LENGTH = 60  # MercadoLibre item title limit.
MAX_PICTURES = 6

# Source name -> adapter factory. Only sources with a real, live adapter
# can be safely mass-published — CJ's wholesale-arbitrage opportunities
# use an estimated (not verified) sell price, so they're deliberately
# excluded until that's addressed.
SUPPORTED_SOURCES: dict[str, type[FalabellaSourceAdapter]] = {
    "Falabella Colombia": FalabellaSourceAdapter,
}


def _truncate_title(name: str) -> str:
    return name if len(name) <= MAX_TITLE_LENGTH else name[: MAX_TITLE_LENGTH - 1].rstrip() + "…"


def main() -> None:
    confirm = "--confirm" in sys.argv[1:]
    init_db()
    db = SessionLocal()
    published, skipped = 0, 0
    try:
        marketplace = db.query(Marketplace).filter_by(name="MercadoLibre Colombia").first()
        if marketplace is None:
            sys.exit("No existe el Marketplace 'MercadoLibre Colombia' — corre discovery primero.")

        opportunities = db.query(Opportunity).filter_by(status=OpportunityStatus.APPROVED).all()
        print(f"{len(opportunities)} oportunidades en estado 'approved'.")
        if not confirm:
            print("*** DRY RUN — no se publicará nada real. Usa --confirm para publicar. ***\n")

        with (
            MercadoLibreAdapter(db) as ml_adapter,
            httpx.Client(
                base_url=category_lookup.API_BASE_URL, timeout=category_lookup.DEFAULT_TIMEOUT
            ) as ml_public_client,
        ):
            if confirm and not ml_adapter.authenticate():
                sys.exit("No hay una cuenta de MercadoLibre conectada/válida.")

            for opp in opportunities:
                product = opp.product
                label = f"[{product.sku}] {product.name[:60]}"

                existing = listing_service.get_listing(db, product.id, marketplace.id)
                if existing is not None and existing.status in (
                    ListingStatus.ACTIVE,
                    ListingStatus.PAUSED,
                ):
                    print(f"SKIP  {label}: ya publicado (external_id={existing.external_id})")
                    skipped += 1
                    continue

                source = db.get(Source, opp.source_id)
                adapter_cls = SUPPORTED_SOURCES.get(source.name if source else "")
                if adapter_cls is None:
                    print(f"SKIP  {label}: fuente '{source.name if source else '?'}' no soportada")
                    skipped += 1
                    continue

                source_product = (
                    db.query(SourceProduct)
                    .filter_by(source_id=opp.source_id, product_id=product.id)
                    .first()
                )
                if source_product is None or not source_product.external_id:
                    print(f"SKIP  {label}: sin SourceProduct.external_id")
                    skipped += 1
                    continue

                with adapter_cls() as source_adapter:
                    live = source_adapter.get_product(source_product.external_id)
                if live is None or not live.stock_available:
                    print(f"SKIP  {label}: ya no disponible en la fuente")
                    skipped += 1
                    continue
                if not live.image_urls:
                    print(f"SKIP  {label}: sin foto real disponible")
                    skipped += 1
                    continue

                category_id = category_lookup.predict_category(
                    product.name, client=ml_public_client
                )
                if category_id is None:
                    print(f"SKIP  {label}: no se pudo predecir categoría")
                    skipped += 1
                    continue
                if not category_lookup.is_safe_to_autopublish(category_id, client=ml_public_client):
                    print(
                        f"SKIP  {label}: categoría {category_id} requiere atributos "
                        "adicionales — revisar manualmente"
                    )
                    skipped += 1
                    continue

                title = _truncate_title(product.name)
                pictures = list(live.image_urls[:MAX_PICTURES])
                print(
                    f"{'PUBLICAR' if confirm else 'PUBLICARÍA'}  {label}\n"
                    f"       categoria={category_id} precio={opp.sell_price} COP "
                    f"fotos={len(pictures)}"
                )
                published += 1

                if confirm:
                    record = listing_service.publish_and_record(
                        db,
                        ml_adapter,
                        product.id,
                        marketplace.id,
                        title=title,
                        price=opp.sell_price,
                        currency="COP",
                        category_id=category_id,
                        brand=product.brand or "Genérica",
                        pictures=pictures,
                    )
                    print(f"       -> {record.external_id} {record.url}")

        print(
            f"\n{'Publicadas' if confirm else 'Se publicarían'}: {published}  Omitidas: {skipped}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
