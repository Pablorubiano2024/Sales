"""Runs the real discovery pipeline against CJdropshipping — an actual
supplier, not a demo/mock one (contrast with scripts/discover_demo.py,
which uses DummyJSON).

Requires `CJ_API_KEY` in your `.env` (see backend/app/integrations/
cjdropshipping.py for how to get one). Each query triggers a handful of
real, rate-limited API calls (CJ's documented limit is 1 req/second; the
adapter self-throttles), so this can take a little while for several
queries.

Prices from CJ are in USD; `run_discovery` converts them to COP (via
`services/currency.py` and `Settings.usd_to_cop_rate`) before evaluating
against the COP-denominated thresholds — update `USD_TO_COP_RATE` in your
.env if it's drifted from the official TRM.

`run_discovery` also subtracts an estimated marketplace commission and
shipping cost (Settings.marketplace_commission_pct / shipping_cost_cop) —
these are single configurable estimates, not a real per-category ML fee or
a real CJ freight quote, so net_profit here is a realistic ballpark, not
an exact number. Verify manually before listing anything with real money.

Usage:
    python scripts/discover_cj.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.config import get_settings  # noqa: E402
from backend.app.core.database import SessionLocal, init_db  # noqa: E402
from backend.app.core.logging import get_logger  # noqa: E402
from backend.app.integrations.cjdropshipping import CJDropshippingAdapter  # noqa: E402
from backend.app.jobs.discovery import run_discovery  # noqa: E402
from backend.app.models.marketplace import Marketplace  # noqa: E402
from backend.app.models.opportunity import Opportunity  # noqa: E402
from backend.app.models.source import Source, SourceType  # noqa: E402

logger = get_logger(__name__)

QUERIES = [
    "wireless earbuds",
    "phone case",
    "smart watch",
    # Higher-ticket categories: the fixed shipping estimate
    # (Settings.shipping_cost_cop) eats a much smaller share of a
    # $150,000+ COP sale than a $3,000 phone case, so these are more
    # likely to survive real cost accounting — see PROJECT_CONTEXT.md,
    # 2026-09-18 findings.
    "mini projector",
    "action camera",
    "bluetooth speaker",
    "gaming keyboard",
    "camera gimbal stabilizer",
    "portable monitor",
]


def main() -> None:
    settings = get_settings()
    if not settings.cj_api_key:
        sys.exit("CJ_API_KEY is not set in your .env — see cjdropshipping.py for how to get one.")

    init_db()
    db = SessionLocal()
    try:
        source = db.query(Source).filter_by(name="CJdropshipping").first()
        if source is None:
            source = Source(
                name="CJdropshipping",
                source_type=SourceType.API,
                base_url="https://developers.cjdropshipping.com",
                country="CN",
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

        with CJDropshippingAdapter() as adapter:
            opportunity_ids = run_discovery(db, source, adapter, marketplace.id, QUERIES)

        print(f"Discovered/updated {len(opportunity_ids)} opportunities from CJdropshipping:")
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
