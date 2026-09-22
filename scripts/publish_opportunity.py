"""Publishes a REAL discovered opportunity on the connected MercadoLibre
account — not a throwaway test item like publish_test_listing.py.

This one: "Household Barrel Portable HM400pro Projector" (CJ pid
2506040836231607700), chosen from the real "promising" opportunities in
`scripts/discover_cj.py`'s output — buy ~$145,326 COP, sell ~$261,587 COP,
net profit ~$48,023 COP, 33% ROI (all already net of the marketplace
commission and shipping estimates — see Settings.marketplace_commission_pct
/ shipping_cost_cop).

Category (MCO11889, "Video Beams" / Proyectores) and its required
attributes (BRAND, MODEL, POWER_SUPPLY_TYPE) were verified live against the
real API on 2026-09-21:
  - GET /sites/MCO/domain_discovery/search?q=proyector+portatil
  - GET /categories/MCO11889/attributes

Pictures are CJ's own real product photos (verified reachable, 200
image/jpeg) — MercadoLibre downloads and hosts its own copy.

This is a REAL, public, live listing that a real buyer could purchase —
unlike the throwaway keychain test item, actually selling this commits to
buying the real product from CJ and shipping it. Run only after explicit
confirmation of the exact payload below.

Usage:
    python scripts/publish_opportunity.py
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.database import SessionLocal, init_db  # noqa: E402
from backend.app.integrations.mercadolibre import MercadoLibreAdapter  # noqa: E402

TITLE = "Proyector Portátil HM400pro 720p 200 ANSI Lumens"
CATEGORY_ID = "MCO11889"  # Video Beams / Proyectores
PRICE = Decimal("261587")  # COP — the opportunity's computed sell_price, rounded
CURRENCY = "COP"
LISTING_TYPE_ID = "free"
BRAND = "Genérica"
MODEL = "HM400pro"
# CJ's own real product photos (verified reachable 2026-09-21).
PICTURES = [
    "https://cf.cjdropshipping.com/quick/product/ed518e71-6ef7-4cf0-8a31-739fcd3e7bde.jpg",
    "https://oss-cf.cjdropshipping.com/product/2025/06/04/08/a05d6431-a92c-4683-a702-1be65f35f754.jpg",
]
EXTRA_ATTRIBUTES = [{"id": "POWER_SUPPLY_TYPE", "value_name": "Corriente doméstica"}]


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        with MercadoLibreAdapter(db) as adapter:
            if not adapter.authenticate():
                sys.exit("No hay una cuenta de MercadoLibre conectada/válida.")

            print(f"Publicando: {TITLE!r}")
            print(f"  category_id={CATEGORY_ID} price={PRICE} {CURRENCY}")
            listing = adapter.create_listing(
                product_id="cj-2506040836231607700",
                title=TITLE,
                price=PRICE,
                currency=CURRENCY,
                category_id=CATEGORY_ID,
                brand=BRAND,
                model=MODEL,
                listing_type_id=LISTING_TYPE_ID,
                pictures=PICTURES,
                extra_attributes=EXTRA_ATTRIBUTES,
            )
            print(f"Publicado: {listing.external_id} — {listing.url}")
            print(f"Estado: {listing.status}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
