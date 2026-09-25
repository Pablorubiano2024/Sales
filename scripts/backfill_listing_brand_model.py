"""One-off backfill: updates already-published MercadoLibre listings with
the real brand/model/matched attributes that
scripts/publish_approved_opportunities.py now sends on new publishes (see
that script's docstring and category_lookup.match_specifications).

Needed because publishing with BRAND="Genérica"/MODEL="Genérico" on a
real branded product (Samsung Galaxy Watch, Redmi Watch, ...) is a real
MercadoLibre publication-quality hit — confirmed live 2026-09-22, and the
code fix only affects future publishes, not what's already live.

For each MarketplaceProduct row with an external_id: re-fetches the
product live from its source, re-fetches the item's real category_id from
MercadoLibre itself (not re-predicted), and PUTs the real brand/model plus
any safely matched extra attributes — this is additive per MercadoLibre's
own attribute-update semantics (an attribute id present in the payload is
upserted; others already on the item are left alone), verified live by
re-fetching and diffing before/after.

Usage:
    python scripts/backfill_listing_brand_model.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from backend.app.core.database import SessionLocal, init_db  # noqa: E402
from backend.app.core.logging import get_logger  # noqa: E402
from backend.app.integrations.falabella_source import (  # noqa: E402
    FalabellaSourceAdapter,
    HomecenterSourceAdapter,
)
from backend.app.integrations.imusa_source import ImusaSourceAdapter  # noqa: E402
from backend.app.integrations.mercadolibre import MercadoLibreAdapter  # noqa: E402
from backend.app.models.marketplace import MarketplaceProduct  # noqa: E402
from backend.app.models.source import SourceProduct  # noqa: E402
from backend.app.services import category_lookup  # noqa: E402

logger = get_logger(__name__)

SUPPORTED_SOURCE_PREFIXES = {
    "FAL": FalabellaSourceAdapter,
    "HOM": HomecenterSourceAdapter,
    "IMU": ImusaSourceAdapter,
}


def _extract_model(specifications: tuple[tuple[str, str], ...]) -> str | None:
    for name, value in specifications:
        if name.strip().lower() == "modelo":
            return value
    return None


def main() -> None:
    init_db()
    db = SessionLocal()
    updated = skipped = 0
    try:
        listings = (
            db.query(MarketplaceProduct).filter(MarketplaceProduct.external_id.isnot(None)).all()
        )
        print(f"{len(listings)} publicaciones con external_id a revisar.")

        with (
            MercadoLibreAdapter(db) as ml_adapter,
            httpx.Client(
                base_url=category_lookup.API_BASE_URL, timeout=category_lookup.DEFAULT_TIMEOUT
            ) as ml_public_client,
        ):
            if not ml_adapter.authenticate():
                sys.exit("No hay una cuenta de MercadoLibre conectada/válida.")
            token = ml_adapter._access_token  # noqa: SLF001
            ml_client = httpx.Client(base_url="https://api.mercadolibre.com", timeout=15)

            for listing in listings:
                product = listing.product
                label = f"[{product.sku}] {product.name[:60]}"

                adapter_cls = SUPPORTED_SOURCE_PREFIXES.get(product.sku.split("-")[0])
                if adapter_cls is None:
                    print(f"SKIP  {label}: fuente no soportada")
                    skipped += 1
                    continue

                source_product = db.query(SourceProduct).filter_by(product_id=product.id).first()
                if source_product is None or not source_product.external_id:
                    print(f"SKIP  {label}: sin SourceProduct.external_id")
                    skipped += 1
                    continue

                with adapter_cls() as source_adapter:
                    live = source_adapter.get_product(source_product.external_id)
                if live is None:
                    print(f"SKIP  {label}: ya no disponible en la fuente")
                    skipped += 1
                    continue

                item_resp = ml_client.get(
                    f"/items/{listing.external_id}", headers={"Authorization": f"Bearer {token}"}
                )
                if item_resp.status_code != 200:
                    print(f"SKIP  {label}: no se pudo leer el item real ({item_resp.status_code})")
                    skipped += 1
                    continue
                category_id = item_resp.json()["category_id"]

                brand = live.brand or product.brand or "Genérica"
                model = _extract_model(live.specifications) or "Genérico"
                extra_attributes = category_lookup.match_specifications(
                    category_id, live.specifications, client=ml_public_client
                )
                attributes = [
                    {"id": "BRAND", "value_name": brand},
                    {"id": "MODEL", "value_name": model},
                    *extra_attributes,
                ]

                put_resp = ml_client.put(
                    f"/items/{listing.external_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"attributes": attributes},
                )
                if put_resp.status_code != 200:
                    print(f"ERROR {label}: {put_resp.status_code} {put_resp.text[:300]}")
                    skipped += 1
                    continue

                print(
                    f"OK    {label}: marca={brand} modelo={model} "
                    f"atributos_extra={len(extra_attributes)}"
                )
                updated += 1

            ml_client.close()

        print(f"\nActualizadas: {updated}  Omitidas: {skipped}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
