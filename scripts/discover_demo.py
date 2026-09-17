"""Demonstrates the discovery pipeline against a REAL HTTP source.

Unlike scripts/seed.py (which inserts hand-picked fictional data directly),
this script exercises the actual `SourceAdapter` -> `run_discovery` pipeline
end-to-end using `DummyJsonSourceAdapter`, a real (if non-production) HTTP
integration — see backend/app/integrations/dummyjson_source.py for why
DummyJSON specifically, and its limitations (USD prices, demo data, not a
real Colombian supplier).

Usage:
    python scripts/discover_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.database import SessionLocal, init_db  # noqa: E402
from backend.app.core.logging import get_logger  # noqa: E402
from backend.app.integrations.dummyjson_source import DummyJsonSourceAdapter  # noqa: E402
from backend.app.jobs.discovery import run_discovery  # noqa: E402
from backend.app.models.marketplace import Marketplace  # noqa: E402
from backend.app.models.opportunity import Opportunity  # noqa: E402
from backend.app.models.source import Source, SourceType  # noqa: E402

logger = get_logger(__name__)

QUERIES = ["phone", "headphones", "watch"]


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        source = db.query(Source).filter_by(name="DummyJSON Demo API").first()
        if source is None:
            source = Source(
                name="DummyJSON Demo API",
                source_type=SourceType.API,
                base_url="https://dummyjson.com",
                country="US",  # demo data, not Colombia-specific
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

        with DummyJsonSourceAdapter() as adapter:
            opportunity_ids = run_discovery(db, source, adapter, marketplace.id, QUERIES)

        print(f"Discovered/updated {len(opportunity_ids)} opportunities via real HTTP calls:")
        for opp_id in opportunity_ids:
            opp = db.get(Opportunity, opp_id)
            if opp is not None:
                print(
                    f"  - {opp.product.name}: buy={opp.buy_price} sell={opp.sell_price} "
                    f"net_profit={opp.net_profit} status={opp.status.value}"
                )
    finally:
        db.close()


if __name__ == "__main__":
    main()
