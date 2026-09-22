"""Runs the real discovery pipeline against falabella.com.co — a genuine
Colombian retail source, not an official supplier API (Falabella doesn't
offer one to individual sellers). See
backend/app/integrations/falabella_source.py's docstring for exactly what
was verified live before writing it (robots.txt, the embedded __NEXT_DATA__
JSON shape on search/product pages).

Important business-model difference from CJdropshipping: this is retail
arbitrage, not dropshipping. Falabella has no supplier-ships-to-your-
customer flow — buying and shipping a Falabella-sourced item is a manual
step you'd do yourself after a sale, briefly holding the item, not the
"never hold inventory" flow the rest of this platform assumes for CJ.

Because fulfillment here is domestic (no international freight), this
overrides the CJ-tuned `Settings.shipping_cost_cop` (~$70,700, calibrated
for CJ's China->Colombia freight) and `Settings.min_buy_price_cop`
($250,000, calibrated to survive that freight cost) with much lower
domestic-shipping estimates — see the constants below. Both are still
single flat estimates, not real per-order courier quotes.

Usage:
    python scripts/discover_falabella.py
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.database import SessionLocal, init_db  # noqa: E402
from backend.app.core.logging import get_logger  # noqa: E402
from backend.app.integrations.falabella_source import FalabellaSourceAdapter  # noqa: E402
from backend.app.jobs.discovery import run_discovery  # noqa: E402
from backend.app.models.marketplace import Marketplace  # noqa: E402
from backend.app.models.opportunity import Opportunity  # noqa: E402
from backend.app.models.source import Source, SourceType  # noqa: E402

logger = get_logger(__name__)

QUERIES = [
    "television",
    "audifonos bluetooth",
    "aspiradora",
    "licuadora",
    "freidora de aire",
    "smartwatch",
]

# Estimated domestic courier cost (Servientrega/Coordinadora/Interrapidísimo
# range for a small-to-medium package) — NOT verified against a real
# quote, unlike CJ's freight-calculator-derived number. Update if you have
# a real courier rate.
DOMESTIC_SHIPPING_COST_COP = Decimal("15000")
# No CJ-style international-freight floor applies here — let real
# ROI/net_profit thresholds do the filtering instead of a price floor.
MIN_BUY_PRICE_COP = Decimal("0")


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        source = db.query(Source).filter_by(name="Falabella Colombia").first()
        if source is None:
            source = Source(
                name="Falabella Colombia",
                source_type=SourceType.SCRAPER,
                base_url="https://www.falabella.com.co",
                country="CO",
            )
            db.add(source)
            db.commit()
            db.refresh(source)

        marketplace = db.query(Marketplace).filter_by(name="MercadoLibre Colombia").first()
        if marketplace is None:
            marketplace = Marketplace(name="MercadoLibre Colombia", country="CO")
            db.add(marketplace)
            db.commit()
            db.refresh(marketplace)

        with FalabellaSourceAdapter() as adapter:
            opportunity_ids = run_discovery(
                db,
                source,
                adapter,
                marketplace.id,
                QUERIES,
                shipping_cost_cop=DOMESTIC_SHIPPING_COST_COP,
                min_buy_price_cop=MIN_BUY_PRICE_COP,
            )

        print(f"Discovered/updated {len(opportunity_ids)} opportunities from Falabella:")
        for opp_id in opportunity_ids:
            opp = db.get(Opportunity, opp_id)
            if opp is not None:
                print(
                    f"  - {opp.product.name[:60]}: buy=${opp.buy_price} COP "
                    f"sell=${opp.sell_price} COP net_profit=${opp.net_profit} COP "
                    f"roi={opp.roi} status={opp.status.value}"
                )
    finally:
        db.close()


if __name__ == "__main__":
    main()
