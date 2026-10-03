"""Listing Draft service (Autopilot Phase 3).

Turns an approved, validated Opportunity into a ListingDraft (title,
description, bullets, attributes, category, images) WITHOUT publishing
anything real. Reuses category_lookup.py's real MercadoLibre category/
attribute/commission lookups — the single source of truth for that logic.

This is also now the content source scripts/publish_approved_opportunities.py
publishes from (title/category_id/brand/model/pictures/extra_attributes) —
that script no longer predicts category or extracts brand/model itself,
it calls `generate_draft` and reads the result, so there's exactly one
place that logic lives. A human can still review/approve/reject a draft
in Streamlit before it's published, but since the user asked for fully
automatic publishing (no click required), the real publish loop doesn't
wait on `approve_draft` — it only ever respects an explicit REJECTED
status (a human override), never auto-regenerating/republishing over one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from backend.app.core.logging import get_logger
from backend.app.integrations.alkosto_source import AlkostoSourceAdapter, KtronixSourceAdapter
from backend.app.integrations.base import SourceAdapter, SourceProductInfo
from backend.app.integrations.falabella_source import (
    FalabellaSourceAdapter,
    HomecenterSourceAdapter,
)
from backend.app.integrations.imusa_source import ImusaSourceAdapter, JumboSourceAdapter
from backend.app.models.listing_draft import ListingDraft, ListingDraftStatus
from backend.app.models.opportunity import Opportunity
from backend.app.models.source import Source, SourceProduct
from backend.app.services import category_lookup

logger = get_logger(__name__)

MAX_TITLE_LENGTH = 60  # MercadoLibre item title limit.
MAX_PICTURES = 6
MAX_DESCRIPTION_SPECS = 20  # avoid an unbounded description for products with huge spec tables.

# Source name -> adapter factory. Only sources with a real, live adapter
# can be safely used here — CJ's wholesale-arbitrage opportunities use an
# estimated (not verified) sell price, so they're deliberately excluded
# until that's addressed. Single source of truth — both
# scripts/publish_approved_opportunities.py and the draft-generation API
# flow import this rather than keeping their own copy.
SUPPORTED_SOURCES: dict[str, type[SourceAdapter]] = {
    "Falabella Colombia": FalabellaSourceAdapter,
    "Homecenter Colombia": HomecenterSourceAdapter,
    "Imusa Colombia": ImusaSourceAdapter,
    "Jumbo Colombia": JumboSourceAdapter,
    "Alkosto Colombia": AlkostoSourceAdapter,
    "Ktronix Colombia": KtronixSourceAdapter,
}


def truncate_title(name: str) -> str:
    return name if len(name) <= MAX_TITLE_LENGTH else name[: MAX_TITLE_LENGTH - 1].rstrip() + "…"


def extract_model(specifications: tuple[tuple[str, str], ...]) -> str | None:
    """Real model number/name from the source's own spec table (e.g.
    Falabella's "Modelo": "SM L320NZSALTA"), instead of a "Genérico"
    placeholder — publishing a real branded product with a generic
    brand/model hurt MercadoLibre's quality score, confirmed live
    2026-09-22."""
    for name, value in specifications:
        if name.strip().lower() == "modelo":
            return value
    return None


@dataclass(frozen=True, slots=True)
class DraftGenerationError:
    reason: str


def fetch_live_source_data(
    db: Session, opportunity: Opportunity
) -> SourceProductInfo | DraftGenerationError:
    """Resolve the right SourceAdapter for this Opportunity's source and
    fetch the current, real product data — the same fetch + stock + photo
    checks scripts/publish_approved_opportunities.py already performs per
    item, factored out so draft generation doesn't duplicate it."""
    source = db.get(Source, opportunity.source_id)
    adapter_cls = SUPPORTED_SOURCES.get(source.name if source else "")
    if adapter_cls is None:
        return DraftGenerationError(f"Fuente '{source.name if source else '?'}' no soportada")

    source_product = (
        db.query(SourceProduct)
        .filter_by(source_id=opportunity.source_id, product_id=opportunity.product_id)
        .first()
    )
    if source_product is None or not source_product.external_id:
        return DraftGenerationError("Sin SourceProduct.external_id para esta oportunidad")

    with adapter_cls() as adapter:
        live = adapter.get_product(source_product.external_id)
    if live is None or not live.stock_available:
        return DraftGenerationError("El producto ya no está disponible en la fuente")
    if not live.image_urls:
        return DraftGenerationError("Sin foto real disponible en la fuente")
    return live


def generate_draft(
    db: Session,
    opportunity: Opportunity,
    live: SourceProductInfo,
    *,
    ml_public_client: httpx.Client,
    access_token: str | None = None,
    listing_type_id: str = "gold_special",
) -> ListingDraft | DraftGenerationError:
    """Build (or refresh) a ListingDraft from the real Product and the
    live source data already fetched by the caller (same `live` shape
    scripts/publish_approved_opportunities.py fetches via a SourceAdapter).
    Never invents specs/images — anything missing on `live` is simply
    omitted. Returns a DraftGenerationError (not raised) when the category
    can't be safely predicted or needs attributes we can't safely supply —
    same skip conditions that script already applies before a real
    publish, surfaced here instead so a human sees why."""
    product = opportunity.product
    real_name = live.name or product.name
    title = truncate_title(real_name)

    # Falabella's search-result name (what discovery stores on
    # Product.name) and its detail-page name can genuinely differ — e.g.
    # a real product's search listing omitted "Imusa" that its own detail
    # page includes. The detail page (`live`, already fetched by the
    # caller) is the richer, more current one — prefer it here and sync
    # it back onto the catalog so it stays accurate for every future
    # caller, not just this draft.
    if real_name != product.name:
        product.name = real_name
        db.commit()

    category_id = category_lookup.predict_category(real_name, client=ml_public_client)
    if category_id is None:
        return DraftGenerationError("No se pudo predecir una categoría real para este producto")

    # Computed before the safety gate below (not after, as before) — a
    # required attribute this product's own real specifications actually
    # matched should count as covered, not just BRAND/MODEL. See
    # category_lookup.is_safe_to_autopublish's 2026-10-03 docstring note.
    # (GTIN/EMPTY_GTIN_REASON deliberately never covered this way — see
    # that same docstring for the real, live-confirmed-negative test.)
    extra_attributes = category_lookup.match_specifications(
        category_id, live.specifications, client=ml_public_client
    )
    covered_attribute_ids = frozenset(a["id"] for a in extra_attributes)

    if not category_lookup.is_safe_to_autopublish(
        category_id, client=ml_public_client, extra_covered_ids=covered_attribute_ids
    ):
        return DraftGenerationError(
            f"Categoría {category_id} requiere atributos que no podemos completar automáticamente"
        )

    brand = live.brand or product.brand or "Genérica"
    model = extract_model(live.specifications) or "Genérico"

    specs = live.specifications[:MAX_DESCRIPTION_SPECS]
    bullets = [f"{name}: {value}" for name, value in specs[:6]]
    description = "\n".join(
        [real_name, "", "Especificaciones:", *(f"- {name}: {value}" for name, value in specs)]
    )

    commission_pct = None
    if access_token is not None:
        commission_pct = category_lookup.get_sale_commission_pct(
            category_id,
            opportunity.sell_price,
            client=ml_public_client,
            access_token=access_token,
            listing_type_id=listing_type_id,
        )

    draft = db.query(ListingDraft).filter_by(opportunity_id=opportunity.id).first()
    if draft is None:
        draft = ListingDraft(opportunity_id=opportunity.id)
        db.add(draft)

    draft.title = title
    draft.description = description
    draft.bullets = json.dumps(bullets)
    draft.attributes = json.dumps(
        {
            "brand": brand,
            "model": model,
            "extra": extra_attributes,
            "commission_pct": float(commission_pct) if commission_pct is not None else None,
        }
    )
    draft.image_urls = json.dumps(list(live.image_urls[:MAX_PICTURES]))
    draft.category_id = category_id
    draft.price = opportunity.sell_price
    if draft.status == ListingDraftStatus.REJECTED:
        draft.status = ListingDraftStatus.DRAFT
        draft.rejection_reason = None
    db.commit()
    db.refresh(draft)
    logger.info(
        "Listing draft generated for opportunity=%s category=%s", opportunity.id, category_id
    )
    return draft


def approve_draft(db: Session, draft: ListingDraft) -> ListingDraft:
    """Draft -> Ready. Informational/manual-review only now that
    publishing is fully automatic (the publish loop doesn't check for
    READY before publishing) — still useful for a human reviewing the
    Streamlit queue to mark something as looked-at."""
    draft.status = ListingDraftStatus.READY
    db.commit()
    db.refresh(draft)
    return draft


def reject_draft(db: Session, draft: ListingDraft, reason: str) -> ListingDraft:
    """The one real override: the automatic publish loop in
    scripts/publish_approved_opportunities.py skips any Opportunity whose
    draft is REJECTED and never auto-regenerates it — a human's "no"
    here sticks until someone calls `generate_draft` again explicitly."""
    draft.status = ListingDraftStatus.REJECTED
    draft.rejection_reason = reason
    db.commit()
    db.refresh(draft)
    return draft
