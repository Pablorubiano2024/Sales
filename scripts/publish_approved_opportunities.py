"""Publishes every real "approved" Opportunity to MercadoLibre —
FULLY AUTOMATIC, no human approval step required (explicit user decision,
2026-10-01: "totalmente automático, sin clics"). A human can still review
drafts in the Streamlit Autopilot view and reject one; that's the one
override this respects (see step 3).

Step 1 of the "publicar + sincronizar a diario" plan: this runs BEFORE the
daily sync job takes over the listing's lifecycle
(scripts/sync_marketplace_listings.py — pauses it if the source product
disappears/reclassifies, updates price if it changes).

For each APPROVED opportunity, in order:
  1. Skip if already published (an active/paused MarketplaceProduct row
     for this product+marketplace already exists) — republishing isn't
     needed, the sync job keeps it current.
  2. Skip if a human already rejected this opportunity's draft in the
     Streamlit Autopilot view — the only real human override; never
     auto-regenerated/republished over.
  3. Re-fetch the product live from its source (currently only Falabella
     has a real adapter) — skip if it went out of stock or disappeared
     since discovery, rather than publish something already invalid.
  4. Generate (or refresh) its ListingDraft via listing_draft_service.
     generate_draft() — real category prediction, safe-attribute check,
     real brand/model/spec-attribute mapping, and the real category-
     specific "Clásica" (gold_special) sale commission, all in that one
     module (not duplicated here).
  5. Recompute the opportunity against that real commission — skip if
     it's no longer actually profitable under the real fee, not the flat
     estimate discovery used.
  6. Run the Opportunity Validator (Phase 1) against the real stock/price
     already fetched in step 3.
  7. Publish via listing_service.publish_and_record(), using the draft's
     real title/category/brand/model/pictures/extra_attributes — which
     also records the MarketplaceProduct row the sync job depends on.

Publishes under "Clásica" (gold_special), not "free": the free tier's
quota is a real, scarce cap shared across every free listing the account
holds at once (confirmed live 2026-09-25 — it dropped from 10 to 1 after
publishing 10 real items and doesn't reset daily), so it can't support
ongoing daily publishing. Clásica has no such cap, at the cost of a real
sale commission instead of $0 — step 5 makes sure that's still covered.

DRY RUN BY DEFAULT — prints exactly what would happen (publish vs. skip +
reason) without creating any real listing. Real MercadoLibre has no
sandbox: every publish here is a genuine, public, live item a real buyer
could purchase. Pass --confirm to actually publish. Note: even a dry run
now authenticates (a read-only token verify/refresh) because step 4 needs
a bearer token for the real commission lookup.

Usage:
    python scripts/publish_approved_opportunities.py            # dry run
    python scripts/publish_approved_opportunities.py --confirm  # for real
"""

from __future__ import annotations

import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json  # noqa: E402

import httpx  # noqa: E402

from backend.app.core.database import SessionLocal, init_db  # noqa: E402
from backend.app.core.logging import get_logger  # noqa: E402
from backend.app.integrations.mercadolibre import MercadoLibreAdapter  # noqa: E402
from backend.app.models.analytics import AnalyticsEvent, AnalyticsEventType  # noqa: E402
from backend.app.models.lifecycle import LifecycleStage, OpportunityLifecycleEvent  # noqa: E402
from backend.app.models.listing_draft import ListingDraft, ListingDraftStatus  # noqa: E402
from backend.app.models.marketplace import ListingStatus, Marketplace  # noqa: E402
from backend.app.models.opportunity import Opportunity, OpportunityStatus  # noqa: E402
from backend.app.schemas.opportunity import OpportunityCreate  # noqa: E402
from backend.app.services import category_lookup, listing_service  # noqa: E402
from backend.app.services.arbitrage_engine import evaluate_opportunity  # noqa: E402
from backend.app.services.listing_draft_service import (  # noqa: E402
    DraftGenerationError,
    fetch_live_source_data,
    generate_draft,
)
from backend.app.services.opportunity_validator import validate_opportunity  # noqa: E402

logger = get_logger(__name__)

# "Free" (Gratuita) has a real, scarce quota shared across ALL free
# listings the account holds at once (confirmed live 2026-09-25: it
# dropped from 10 to 1 after publishing 10 real items and never
# recovered) — not a per-day allowance, so it can't support daily
# publishing. "Clásica" (gold_special) has no such cap, at the cost of a
# real, category-specific sale commission (see get_sale_commission_pct
# below) instead of $0.
LISTING_TYPE_ID = "gold_special"
# Seen so far only while the account still had free-tier listings in
# flight, but kept as a general defensive retry for any listing_type —
# confirmed live 2026-09-22, see the retry loop below.
RATE_LIMIT_BACKOFF_SECONDS = 30
MAX_RATE_LIMIT_RETRIES = 3


def main() -> None:
    confirm = "--confirm" in sys.argv[1:]
    init_db()
    db = SessionLocal()
    published, skipped = 0, 0
    try:
        marketplace = db.query(Marketplace).filter_by(name="MercadoLibre Colombia").first()
        if marketplace is None:
            sys.exit("No existe el Marketplace 'MercadoLibre Colombia' — corre discovery primero.")

        opportunities = db.query(Opportunity).filter_by(status=OpportunityStatus.APPROVED).all()
        print(f"{len(opportunities)} oportunidades en estado 'approved'.")
        if not confirm:
            print("*** DRY RUN — no se publicará nada real. Usa --confirm para publicar. ***\n")

        with (
            MercadoLibreAdapter(db) as ml_adapter,
            httpx.Client(
                base_url=category_lookup.API_BASE_URL, timeout=category_lookup.DEFAULT_TIMEOUT
            ) as ml_public_client,
        ):
            # Authenticate even in a dry run — computing the real,
            # category-specific sale commission below needs a bearer
            # token (verified live 2026-09-25: /sites/MCO/listing_prices
            # now requires auth). Authenticating is a read-only token
            # refresh/verify, not a write.
            if not ml_adapter.authenticate() or ml_adapter._access_token is None:  # noqa: SLF001
                sys.exit("No hay una cuenta de MercadoLibre conectada/válida.")
            access_token: str = ml_adapter._access_token  # noqa: SLF001

            for opp in opportunities:
                product = opp.product
                label = f"[{product.sku}] {product.name[:60]}"

                existing = listing_service.get_listing(db, product.id, marketplace.id)
                if existing is not None and existing.status in (
                    ListingStatus.ACTIVE,
                    ListingStatus.PAUSED,
                ):
                    print(f"SKIP  {label}: ya publicado (external_id={existing.external_id})")
                    skipped += 1
                    continue

                # The one real human override: a draft a human explicitly
                # rejected in the Streamlit Autopilot view stays rejected —
                # never auto-regenerated/republished over.
                existing_draft = db.query(ListingDraft).filter_by(opportunity_id=opp.id).first()
                if (
                    existing_draft is not None
                    and existing_draft.status == ListingDraftStatus.REJECTED
                ):
                    print(f"SKIP  {label}: borrador rechazado manualmente, no se reintenta")
                    skipped += 1
                    continue

                live_or_error = fetch_live_source_data(db, opp)
                if isinstance(live_or_error, DraftGenerationError):
                    print(f"SKIP  {label}: {live_or_error.reason}")
                    skipped += 1
                    continue
                live = live_or_error

                # Real category prediction, safe-attribute check, real
                # brand/model/spec mapping, and the real category-specific
                # commission — all computed by listing_draft_service, the
                # single source of truth for this logic (not duplicated
                # here). Also syncs Product.name from the live detail page.
                draft_or_error = generate_draft(
                    db,
                    opp,
                    live,
                    ml_public_client=ml_public_client,
                    access_token=access_token,
                    listing_type_id=LISTING_TYPE_ID,
                )
                if isinstance(draft_or_error, DraftGenerationError):
                    print(f"SKIP  {label}: {draft_or_error.reason}")
                    skipped += 1
                    continue
                draft = draft_or_error
                attrs = json.loads(draft.attributes or "{}")

                # The real "Clásica" commission is category-specific (16.5%
                # for Freidoras vs 12.0% for Relojes, confirmed live
                # 2026-09-25) — recompute against it now rather than trust
                # discovery's flat Settings.marketplace_commission_pct
                # estimate, and skip if it's no longer actually profitable
                # under the real fee. evaluate_opportunity upserts the same
                # Opportunity row, so this also corrects it going forward.
                real_commission_pct = attrs.get("commission_pct")
                if real_commission_pct is not None:
                    real_fee = (opp.sell_price * Decimal(str(real_commission_pct))).quantize(
                        Decimal("0.01")
                    )
                    opp = evaluate_opportunity(
                        db,
                        OpportunityCreate(
                            product_id=product.id,
                            source_id=opp.source_id,
                            marketplace_id=marketplace.id,
                            buy_price=float(opp.buy_price),
                            sell_price=float(opp.sell_price),
                            marketplace_fee=float(real_fee),
                            shipping_cost=float(opp.shipping_cost),
                            tax_cost=float(opp.tax_cost),
                            payment_cost=float(opp.payment_cost),
                            other_cost=float(opp.other_cost),
                        ),
                    )
                    if opp.status not in (OpportunityStatus.APPROVED, OpportunityStatus.PROMISING):
                        print(
                            f"SKIP  {label}: con comisión real de {LISTING_TYPE_ID} "
                            f"({float(real_commission_pct):.1%}) ya no es rentable "
                            f"(status={opp.status.value})"
                        )
                        skipped += 1
                        continue
                else:
                    logger.warning(
                        "No se pudo obtener la comisión real para categoría=%s; "
                        "usando el estimado de Settings.marketplace_commission_pct",
                        draft.category_id,
                    )

                # Autopilot Phase 1 gate — margin/score/seller_count/stock
                # rules the user asked for, on top of the checks above
                # (which already re-verify stock and the real commission).
                # Reuses the live stock/price this loop already fetched
                # instead of re-querying the source a second time.
                validation = validate_opportunity(
                    db, opp, live_stock_available=live.stock_available, live_price_cop=live.price
                )
                if not validation.overall_passed:
                    reasons = "; ".join(c.detail for c in validation.failed_checks)
                    print(f"SKIP  {label}: no pasó el Opportunity Validator ({reasons})")
                    skipped += 1
                    continue

                pictures = json.loads(draft.image_urls or "[]")
                extra_attributes = attrs.get("extra", [])

                if not confirm:
                    print(
                        f"PUBLICARÍA  {label}\n"
                        f"       categoria={draft.category_id} precio={opp.sell_price} COP "
                        f"fotos={len(pictures)} marca={attrs.get('brand')} "
                        f"modelo={attrs.get('model')} atributos_extra={len(extra_attributes)}"
                    )
                    published += 1
                    continue

                # "listing_type.temporarily_unavailable" is a real cooldown
                # between consecutive free-tier item creations, not a
                # permanent failure — confirmed live 2026-09-22 (an attempt
                # right after a previous success fails, one ~60s later on
                # its own succeeds). Retry with backoff instead of treating
                # it like any other error; any other real error still
                # aborts just this item, not the whole batch.
                record = None
                for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
                    try:
                        record = listing_service.publish_and_record(
                            db,
                            ml_adapter,
                            product.id,
                            marketplace.id,
                            title=draft.title,
                            price=opp.sell_price,
                            currency="COP",
                            category_id=draft.category_id,
                            brand=attrs.get("brand", "Genérica"),
                            model=attrs.get("model", "Genérico"),
                            listing_type_id=LISTING_TYPE_ID,
                            pictures=pictures,
                            extra_attributes=extra_attributes,
                        )
                        break
                    except RuntimeError as exc:
                        is_last = attempt == MAX_RATE_LIMIT_RETRIES
                        if "listing_type.temporarily_unavailable" in str(exc) and not is_last:
                            print(
                                f"       cooldown, reintentando en {RATE_LIMIT_BACKOFF_SECONDS}s..."
                            )
                            time.sleep(RATE_LIMIT_BACKOFF_SECONDS)
                            continue
                        print(f"ERROR  {label}: {exc}")
                        skipped += 1
                        break
                if record is None:
                    continue

                draft.status = ListingDraftStatus.PUBLISHED
                db.add(draft)
                db.add(
                    OpportunityLifecycleEvent(
                        opportunity_id=opp.id,
                        stage=LifecycleStage.PUBLISHED,
                        reason=f"Publicada en MercadoLibre como {record.external_id}",
                    )
                )
                db.add(
                    AnalyticsEvent(
                        opportunity_id=opp.id,
                        event_type=AnalyticsEventType.PUBLISHED,
                        estimated_margin=opp.margin,
                        confidence_score_at_detection=opp.confidence_score,
                    )
                )
                opp.lifecycle_stage = LifecycleStage.PUBLISHED
                db.commit()

                print(
                    f"PUBLICADA  {label}: {record.external_id} {record.url}\n"
                    f"       categoria={draft.category_id} precio={opp.sell_price} COP "
                    f"fotos={len(pictures)}"
                )
                published += 1

        print(
            f"\n{'Publicadas' if confirm else 'Se publicarían'}: {published}  Omitidas: {skipped}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
