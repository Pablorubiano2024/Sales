"""Runs the Market Gap Scanner (Autopilot Phase 4) against real
Opportunities and prints a summary of what changed.

Scans Opportunities in APPROVED or PROMISING status only — the ones
actually worth watching, and the ones we don't want to burn MercadoLibre's
real rate limit on REJECTED/REVIEW opportunities for. For each:
  1. Find (or reuse) its real MercadoLibre catalog_product_id via
     GET /products/search.
  2. Fetch the real current Buy Box state via GET /products/{id}/items —
     see backend/app/services/catalog_lookup.py's docstring for why NOT
     the top-level buy_box_winner field (verified live 2026-09-28: it's
     unreliable, comes back null even with real active competition).
  3. Persist a MarketGapSnapshot, and — only when there's a previous real
     snapshot to compare against — a MarketGapEvent for whatever actually
     changed (LOWEST_SELLER_DISAPPEARED, BUY_BOX_PRICE_INCREASED,
     SELLER_COUNT_DROPPED, STOCK_RECOVERED).

This is READ-ONLY against MercadoLibre — it never publishes, updates, or
deletes anything there, only calls two GET endpoints. No --confirm flag
needed (unlike publish_approved_opportunities.py, which does real writes).

Once real snapshots exist, opportunity_validator.py's seller_count check
and confidence_engine.py's competition factor both automatically start
using this real data instead of their "not applicable yet" / proxy
fallbacks — no further wiring needed there.

Usage:
    python scripts/run_market_gap_scan.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from backend.app.core.database import SessionLocal, init_db  # noqa: E402
from backend.app.core.logging import get_logger  # noqa: E402
from backend.app.integrations.mercadolibre import MercadoLibreAdapter  # noqa: E402
from backend.app.jobs.market_gap_scanner import run_market_gap_scan  # noqa: E402
from backend.app.models.opportunity import Opportunity, OpportunityStatus  # noqa: E402
from backend.app.services import catalog_lookup  # noqa: E402

logger = get_logger(__name__)


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        opportunities = (
            db.query(Opportunity)
            .filter(
                Opportunity.status.in_([OpportunityStatus.APPROVED, OpportunityStatus.PROMISING])
            )
            .all()
        )
        print(f"{len(opportunities)} oportunidades en estado 'approved'/'promising' a escanear.")
        if not opportunities:
            return

        with (
            MercadoLibreAdapter(db) as ml_adapter,
            httpx.Client(
                base_url=catalog_lookup.API_BASE_URL, timeout=catalog_lookup.DEFAULT_TIMEOUT
            ) as ml_public_client,
        ):
            if not ml_adapter.authenticate() or ml_adapter._access_token is None:  # noqa: SLF001
                sys.exit("No hay una cuenta de MercadoLibre conectada/válida.")
            access_token: str = ml_adapter._access_token  # noqa: SLF001

            result = run_market_gap_scan(
                db, opportunities, client=ml_public_client, access_token=access_token
            )

        print(
            f"\nEscaneadas: {result.scanned}  "
            f"Sin match de catálogo/error: {result.skipped_no_catalog_match}  "
            f"Eventos reales detectados: {result.events_detected}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
