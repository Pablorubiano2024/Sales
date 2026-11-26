"""Daily check: is MercadoLibre's competitor-price endpoint back?

Since 2026-11-23, GET /products/{id}/items answers 403 PolicyAgent
("PA_UNAUTHORIZED_RESULT_FROM_POLICIES") for every catalog product, with
or without a token, even after re-authorizing the app on 2026-11-24.
Developer support is closed to non-certified apps ("Canal exclusivo para
integradores certificados del Developer Partner Program"), so there is
nobody to ask; this just watches.

While the block lasts, publishing and reactivation already fail safe
(no competitor evidence = unknown). When it lifts, they pick it up by
themselves; this posts to the sales Slack channel so a person knows to
revisit the no-competitor pilot (publish_approved_opportunities.py). The
message repeats daily while the endpoint works — delete this script and
its workflow step once the pilot has been revisited.

A 404 "No winners found" also means the endpoint answers again (just no
sellers on that product), so anything except the PolicyAgent 403 counts.

Usage:
    python scripts/check_competitor_api.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.config import get_settings  # noqa: E402
from backend.app.core.database import SessionLocal, init_db  # noqa: E402
from backend.app.integrations.mercadolibre import MercadoLibreAdapter  # noqa: E402
from backend.app.models.marketplace import ListingCatalogMatch  # noqa: E402
from backend.app.services.sale_alerts import SlackClient  # noqa: E402

# Catalog products checked on 2026-11-25 (both 403), used when the
# listing_catalog_matches table has none.
FALLBACK_CATALOG_IDS = ["MCO75242471", "MCO80532364"]
PROBES = 3


def is_blocked(status_code: int, body: str) -> bool:
    return status_code == 403 and "PolicyAgent" in body


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        catalog_ids = [
            row.catalog_product_id
            for row in db.query(ListingCatalogMatch).order_by(ListingCatalogMatch.created_at.desc())
        ]
        catalog_ids = list(dict.fromkeys(catalog_ids))[:PROBES] or FALLBACK_CATALOG_IDS

        with MercadoLibreAdapter(db) as ml:
            if not ml.authenticate():
                sys.exit("No hay una cuenta de MercadoLibre conectada/válida.")
            results = []
            for catalog_id in catalog_ids:
                response = ml._client.get(
                    f"/products/{catalog_id}/items",
                    headers={"Authorization": f"Bearer {ml._access_token}"},
                )
                blocked = is_blocked(response.status_code, response.text)
                results.append(blocked)
                print(f"{catalog_id}: {response.status_code} {'BLOQUEADO' if blocked else 'OK'}")

        if all(results):
            print("Precios de competidores: sigue bloqueado (403 PolicyAgent).")
            return

        text = (
            ":white_check_mark: MercadoLibre volvió a responder los *precios de competidores* "
            "(/products/{id}/items ya no da 403). La publicación y las reactivaciones los usan "
            "solas desde ya. Pendiente: revisar el piloto de publicar sin competidores."
        )
        print(text)
        settings = get_settings()
        if settings.slack_bot_token and settings.slack_sales_channel:
            slack = SlackClient(settings.slack_bot_token)
            try:
                slack.post(settings.slack_sales_channel, text)
            finally:
                slack.close()
    finally:
        db.close()


if __name__ == "__main__":
    main()
