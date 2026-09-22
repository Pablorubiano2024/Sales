"""Publishes ONE real test listing on the connected MercadoLibre account.

MercadoLibre has no sandbox (see "Realiza pruebas" in their docs) — this
creates a REAL, public, live item, visible to real MercadoLibre Colombia
users, under the seller account connected via
`/api/marketplaces/mercadolibre/authorize`. It follows MercadoLibre's own
convention for test items (title "Item de Prueba - Por favor, NO OFERTAR",
`listing_type_id="free"` — no cost, no premium visibility).

Category (MCO412060, "Llaveros") and its required attributes (BRAND, MODEL)
were verified live against the real API on 2026-09-21:
  - GET /sites/MCO/domain_discovery/search?q=llavero
  - GET /categories/MCO412060/attributes  (confirms BRAND accepts "Generic")

Run only after reviewing the payload below — this is not reversible via
this script (delete/pause the listing manually in MercadoLibre if needed).

Usage:
    python scripts/publish_test_listing.py
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.database import SessionLocal, init_db  # noqa: E402
from backend.app.integrations.mercadolibre import MercadoLibreAdapter  # noqa: E402

TITLE = "Item de Prueba - Por favor, NO OFERTAR"
CATEGORY_ID = "MCO412060"  # "Llaveros" — verified live, accepts BRAND="Generic"
PRICE = Decimal("5000")  # COP — trivial, well above ML's ~$2,900 COP minimum. Must be a
# whole number: COP rejects any decimal precision (verified live 2026-09-21).
CURRENCY = "COP"
LISTING_TYPE_ID = "free"  # no cost, no premium visibility — requires a picture, hence below.
# A real, licensed (CC-BY-SA), publicly reachable image — verified live
# 2026-09-21 (200 OK, image/jpeg). "bronze" was tried first as a
# no-picture-required alternative, but MercadoLibre silently normalizes it
# to "gold_special" server-side, which does require one — so a real
# picture is simpler and more reliable than chasing tier quirks.
PICTURES = [
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a0/Keychain.jpg/500px-Keychain.jpg"
]


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        with MercadoLibreAdapter(db) as adapter:
            if not adapter.authenticate():
                sys.exit(
                    "No hay una cuenta de MercadoLibre conectada/válida — conecta la cuenta "
                    "primero (ver frontend Marketplaces, o GET /api/marketplaces/mercadolibre/"
                    "authorize)."
                )

            print(f"Publicando: {TITLE!r}")
            print(
                f"  category_id={CATEGORY_ID} price={PRICE} {CURRENCY} "
                f"listing_type={LISTING_TYPE_ID}"
            )
            listing = adapter.create_listing(
                product_id="test",
                title=TITLE,
                price=PRICE,
                currency=CURRENCY,
                category_id=CATEGORY_ID,
                listing_type_id=LISTING_TYPE_ID,
                pictures=PICTURES,
            )
            print(f"Publicado: {listing.external_id} — {listing.url}")
            print(f"Estado: {listing.status}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
