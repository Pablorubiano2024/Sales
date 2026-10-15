"""Applies the Listing Optimizer's one general rule to every ACTIVE (and
the reactivation check to every PAUSED) MercadoLibre listing — see
backend/app/services/listing_optimizer.py for the rule and the hard
ROI/net-profit floor it never goes below.

Runs right AFTER scripts/sync_marketplace_listings.py (same workflow):
sync refreshes each listing's real buy price and pauses anything no longer
viable; this then sets exposure, price and catalog participation from
that fresh buy price.

DRY RUN BY DEFAULT — prints every change it would make. Pass --confirm to
apply them for real on MercadoLibre.

Usage:
    python scripts/optimize_listings.py            # dry run
    python scripts/optimize_listings.py --confirm  # for real
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.config import get_settings  # noqa: E402
from backend.app.core.database import SessionLocal, init_db  # noqa: E402
from backend.app.integrations.mercadolibre import MercadoLibreAdapter  # noqa: E402
from backend.app.models.marketplace import ListingStatus, MarketplaceProduct  # noqa: E402
from backend.app.services.listing_optimizer import (  # noqa: E402
    completed_sales,
    is_launch_mode,
    optimize_listing,
)


def main() -> None:
    confirm = "--confirm" in sys.argv[1:]
    init_db()
    settings = get_settings()
    db = SessionLocal()
    changed = unchanged = paused = reactivated = skipped = failed = 0
    try:
        listings = (
            db.query(MarketplaceProduct)
            .filter(
                MarketplaceProduct.status.in_([ListingStatus.ACTIVE, ListingStatus.PAUSED]),
                MarketplaceProduct.external_id.isnot(None),
            )
            .all()
        )
        print(
            f"{len(listings)} avisos activos/pausados. Mínimos: ROI {settings.min_roi:.0%}, "
            f"ganancia neta {settings.min_net_profit:,.0f} COP."
        )
        if not confirm:
            print("*** DRY RUN — no se cambiará nada real. Usa --confirm para aplicar. ***\n")

        with MercadoLibreAdapter(db) as ml:
            if not ml.authenticate():
                sys.exit("No hay una cuenta de MercadoLibre conectada/válida.")
            launch_mode = is_launch_mode(ml)
            print(
                f"Ventas completadas de la cuenta: {completed_sales(ml)} -> modo "
                f"{'LANZAMIENTO (precio mínimo rentable)' if launch_mode else 'normal'}\n"
            )
            # Active first, so a paused twin of a live listing stays paused.
            listings.sort(key=lambda x: x.status != ListingStatus.ACTIVE)
            live_keys: set[str] = set()
            for listing in listings:
                try:
                    result = optimize_listing(
                        db,
                        ml,
                        listing,
                        settings,
                        apply=confirm,
                        launch_mode=launch_mode,
                        live_keys=live_keys,
                    )
                except Exception as exc:  # one bad listing shouldn't stop the rest
                    db.rollback()
                    print(f"ERROR  {listing.external_id}: {exc}")
                    failed += 1
                    continue
                label = f"{result.external_id} {result.title}"
                if result.skipped:
                    print(f"SKIP   {label}: {result.skipped}")
                    skipped += 1
                elif not result.actions:
                    print(f"OK     {label}: sin cambios")
                    unchanged += 1
                else:
                    paused += result.paused
                    reactivated += result.reactivated
                    changed += not (result.paused or result.reactivated)
                    kind = (
                        "PAUSA" if result.paused else "ACTIVA" if result.reactivated else "CAMBIO"
                    )
                    for action in result.actions:
                        print(f"{kind:6} {label}: {action}")

        print(
            f"\nCambiados: {changed}  Pausados: {paused}  Reactivados: {reactivated}  "
            f"Sin cambios: {unchanged}  "
            f"Omitidos: {skipped}  Errores: {failed}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
