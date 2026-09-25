"""Runs the real discovery pipeline against homecenter.falabella.com.co
(Sodimac/Homecenter, a home-improvement retailer in the Falabella
corporate group) — same retail-arbitrage model as discover_falabella.py,
reusing the shared platform adapter (see
backend/app/integrations/falabella_source.py's module docstring for what
was verified live: identical JSON shape to falabella.com.co, but no
robots.txt exists on this subdomain at all — not an explicit denial, but
also not an explicit grant).

Same domestic-fulfillment overrides as discover_falabella.py (this is
retail arbitrage, not CJ-style dropshipping — no supplier-ships-to-
customer flow, and no international freight to account for).

Usage:
    python scripts/discover_homecenter.py
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.database import SessionLocal, init_db  # noqa: E402
from backend.app.core.logging import get_logger  # noqa: E402
from backend.app.integrations.falabella_source import HomecenterSourceAdapter  # noqa: E402
from backend.app.jobs.discovery import run_discovery  # noqa: E402
from backend.app.models.marketplace import Marketplace  # noqa: E402
from backend.app.models.opportunity import Opportunity  # noqa: E402
from backend.app.models.source import Source, SourceType  # noqa: E402

logger = get_logger(__name__)

QUERIES = [
    "taladro",
    "aspiradora",
    "ventilador",
    "licuadora",
    "freidora de aire",
    "herramientas electricas",
]

DOMESTIC_SHIPPING_COST_COP = Decimal("15000")
MIN_BUY_PRICE_COP = Decimal("0")


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        source = db.query(Source).filter_by(name="Homecenter Colombia").first()
        if source is None:
            source = Source(
                name="Homecenter Colombia",
                source_type=SourceType.SCRAPER,
                base_url="https://homecenter.falabella.com.co",
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

        with HomecenterSourceAdapter() as adapter:
            opportunity_ids = run_discovery(
                db,
                source,
                adapter,
                marketplace.id,
                QUERIES,
                shipping_cost_cop=DOMESTIC_SHIPPING_COST_COP,
                min_buy_price_cop=MIN_BUY_PRICE_COP,
            )

        print(f"Discovered/updated {len(opportunity_ids)} opportunities from Homecenter:")
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
