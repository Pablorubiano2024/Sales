"""Polls real MercadoLibre sales and routes each new one to a supplier
(Sandbox mode — see backend/app/services/order_router.py).

For each real sale not already recorded as an Order:
  1. Map its sold item (order_items[0].item.id) back to our own
     MarketplaceProduct.external_id to find which internal Product sold.
  2. Pick the cheapest real in-stock SourceProduct for that Product.
  3. Create an Order (Sandbox: pure bookkeeping, never touches the
     supplier's site or MercadoLibre for anything but reading the order).

READ-ONLY against MercadoLibre (only GET /orders/search) — no --confirm
flag needed, same as run_market_gap_scan.py. Assisted mode (Playwright
pre-filling a real supplier checkout) is NOT implemented here — see
order_router.py's module docstring for why.

Usage:
    python scripts/run_order_sync.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.database import SessionLocal, init_db  # noqa: E402
from backend.app.core.logging import get_logger  # noqa: E402
from backend.app.integrations.mercadolibre import MercadoLibreAdapter  # noqa: E402
from backend.app.jobs.order_sync import run_order_sync  # noqa: E402

logger = get_logger(__name__)


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        with MercadoLibreAdapter(db) as ml_adapter:
            if not ml_adapter.authenticate():
                sys.exit("No hay una cuenta de MercadoLibre conectada/válida.")
            created = run_order_sync(db, ml_adapter)
        print(f"Órdenes nuevas creadas (modo Sandbox): {created}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
