"""Autopilot Confidence Engine — the star feature the user asked for.

A deterministic, auditable weighted score, NOT a trained ML model: every
point awarded comes with a human-readable reason, matching the user's own
example format ("Margen alto (+28), Poca competencia (+20), ... = Total:
94%"). The system must always show WHY it recommends something.

Weights below are documented constants (same spirit as
Settings.marketplace_commission_pct — real, justified numbers, never a
mystery) and sum to 100 when every factor hits its best case. "Learning
over time" is `recalibrate_weights()`: a periodic, read-only comparison of
past scores against real outcomes in `analytics_events` — it reports
whether the weights are directionally correct, it does not silently
mutate them. Actually adjusting the weights from that report is a
deliberate, versioned code change (Phase 7), never done automatically.

Two factors below only have real data once later Autopilot phases exist:
- competition uses the real Buy Box seller count (Market Gap Scanner,
  Phase 4) when a snapshot exists, otherwise a documented discovery-
  recurrence proxy — never invented data.
- sales history and supplier stability already have real data sources
  today (analytics_events, price_history) and don't need a proxy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.core.time import utcnow
from backend.app.models.analytics import AnalyticsEvent, AnalyticsEventType
from backend.app.models.lifecycle import LifecycleStage, OpportunityLifecycleEvent
from backend.app.models.opportunity import Opportunity
from backend.app.models.price_history import PriceHistory
from backend.app.services.opportunity_validator import get_latest_market_gap_snapshot

# --- Weights (max points per factor when it's at its best) ---
MAX_MARGIN_POINTS = 30
MAX_COMPETITION_POINTS = 20
MAX_SALES_HISTORY_POINTS = 25
MAX_SUPPLIER_STABILITY_POINTS = 15
MAX_RECENCY_POINTS = 10
MAX_TOTAL_SCORE = (
    MAX_MARGIN_POINTS
    + MAX_COMPETITION_POINTS
    + MAX_SALES_HISTORY_POINTS
    + MAX_SUPPLIER_STABILITY_POINTS
    + MAX_RECENCY_POINTS
)

PRICE_HISTORY_WINDOW = 10  # most recent PriceHistory rows considered for supplier stability
RECENCY_FULL_POINTS_WITHIN = timedelta(hours=24)
RECENCY_PARTIAL_POINTS_WITHIN = timedelta(days=3)
RECENCY_LOW_POINTS_WITHIN = timedelta(days=14)


@dataclass(frozen=True, slots=True)
class ConfidenceFactor:
    label: str
    points: int
    reasoning: str


@dataclass(frozen=True, slots=True)
class ConfidenceScore:
    score: int
    breakdown: list[ConfidenceFactor] = field(default_factory=list)

    def explanation(self) -> str:
        """Human-readable line matching the user's own requested format."""
        parts = [f"{f.label} (+{f.points})" for f in self.breakdown if f.points > 0]
        return (", ".join(parts) if parts else "Sin puntos") + f" = Total: {self.score}%"

    def to_json(self) -> str:
        return json.dumps(
            [
                {"label": f.label, "points": f.points, "reasoning": f.reasoning}
                for f in self.breakdown
            ]
        )


def _margin_factor(opportunity: Opportunity) -> ConfidenceFactor:
    margin = opportunity.margin
    if margin >= Decimal("0.40"):
        points = MAX_MARGIN_POINTS
        label = "Margen muy alto"
    elif margin >= Decimal("0.30"):
        points = 24
        label = "Margen alto"
    elif margin >= Decimal("0.20"):
        points = 16
        label = "Margen aceptable"
    elif margin >= Decimal("0.10"):
        points = 8
        label = "Margen bajo"
    else:
        points = 0
        label = "Margen insuficiente"
    return ConfidenceFactor(label=label, points=points, reasoning=f"margin={margin:.2%}")


def _competition_factor(db: Session, opportunity: Opportunity) -> ConfidenceFactor:
    snapshot = get_latest_market_gap_snapshot(db, opportunity.id)
    if snapshot is not None:
        seller_count = snapshot.seller_count
        if seller_count <= 3:
            points, label = MAX_COMPETITION_POINTS, "Poca competencia (Buy Box real)"
        elif seller_count <= 8:
            points, label = 12, "Competencia moderada (Buy Box real)"
        elif seller_count <= 15:
            points, label = 6, "Competencia alta (Buy Box real)"
        else:
            points, label = 0, "Competencia muy alta (Buy Box real)"
        return ConfidenceFactor(
            label=label, points=points, reasoning=f"seller_count={seller_count} (snapshot real)"
        )

    # No real Buy Box snapshot yet (Market Gap Scanner, Phase 4, not built).
    # Documented proxy: how many times this exact product has already
    # produced an Opportunity across any source — a product discovered
    # repeatedly is more likely to already be widely sold, so it scores
    # lower here than one seen for the first time. Explicitly weaker/lower-
    # confidence than the real Buy Box count above (max 14 vs 20 points).
    recurrence = (
        db.query(Opportunity).filter(Opportunity.product_id == opportunity.product_id).count()
    )
    if recurrence <= 1:
        points, label = 14, "Producto poco frecuente en discovery (proxy)"
    elif recurrence <= 3:
        points, label = 8, "Producto con frecuencia moderada en discovery (proxy)"
    else:
        points, label = 2, "Producto muy frecuente en discovery (proxy)"
    return ConfidenceFactor(
        label=label,
        points=points,
        reasoning=(
            f"recurrence={recurrence} oportunidades para este producto "
            "(proxy: sin snapshot real de Buy Box todavía)"
        ),
    )


def _sales_history_factor(db: Session, opportunity: Opportunity) -> ConfidenceFactor:
    sold_count = (
        db.query(AnalyticsEvent)
        .join(Opportunity, AnalyticsEvent.opportunity_id == Opportunity.id)
        .filter(
            Opportunity.product_id == opportunity.product_id,
            AnalyticsEvent.event_type == AnalyticsEventType.SOLD,
        )
        .count()
    )
    if sold_count == 0:
        points, label = 0, "Sin historial de ventas reales para este producto"
    elif sold_count <= 2:
        points, label = 14, "Producto con ventas históricas limitadas"
    elif sold_count <= 5:
        points, label = 20, "Producto con ventas históricas"
    else:
        points, label = MAX_SALES_HISTORY_POINTS, "Producto con historial de ventas consolidado"
    return ConfidenceFactor(label=label, points=points, reasoning=f"ventas_reales={sold_count}")


def _supplier_stability_factor(db: Session, opportunity: Opportunity) -> ConfidenceFactor:
    rows = (
        db.query(PriceHistory.price)
        .filter_by(product_id=opportunity.product_id, source_id=opportunity.source_id)
        .order_by(PriceHistory.captured_at.desc())
        .limit(PRICE_HISTORY_WINDOW)
        .all()
    )
    if not rows:
        return ConfidenceFactor(
            label="Sin historial de precios del proveedor todavía",
            points=0,
            reasoning="price_history vacío para este proveedor",
        )
    distinct_prices = len({r[0] for r in rows})
    if distinct_prices == 1:
        points, label = MAX_SUPPLIER_STABILITY_POINTS, "Proveedor estable"
    elif distinct_prices <= 2:
        points, label = 9, "Proveedor con cambios de precio ocasionales"
    else:
        points, label = 3, "Proveedor con precio inestable"
    reasoning = f"{distinct_prices} precio(s) distinto(s) en las últimas {len(rows)} verificaciones"
    return ConfidenceFactor(label=label, points=points, reasoning=reasoning)


def _found_at(db: Session, opportunity: Opportunity) -> datetime:
    first_found = (
        db.query(OpportunityLifecycleEvent)
        .filter_by(opportunity_id=opportunity.id, stage=LifecycleStage.FOUND)
        .order_by(OpportunityLifecycleEvent.occurred_at.asc())
        .first()
    )
    return first_found.occurred_at if first_found is not None else opportunity.created_at


def _recency_factor(db: Session, opportunity: Opportunity) -> ConfidenceFactor:
    found_at = _found_at(db, opportunity)
    age = utcnow() - found_at
    if age <= RECENCY_FULL_POINTS_WITHIN:
        points, label = MAX_RECENCY_POINTS, "Gap recién detectado"
    elif age <= RECENCY_PARTIAL_POINTS_WITHIN:
        points, label = 6, "Gap detectado recientemente"
    elif age <= RECENCY_LOW_POINTS_WITHIN:
        points, label = 3, "Gap detectado hace más de 3 días"
    else:
        points, label = 0, "Gap detectado hace más de 14 días, probablemente ya no vigente"
    return ConfidenceFactor(label=label, points=points, reasoning=f"detectado hace {age}")


def compute_confidence(db: Session, opportunity: Opportunity) -> ConfidenceScore:
    """Pure computation — no persistence. See `score_opportunity` to
    compute and save in one step, matching ai_service.py's convention."""
    breakdown = [
        _margin_factor(opportunity),
        _competition_factor(db, opportunity),
        _sales_history_factor(db, opportunity),
        _supplier_stability_factor(db, opportunity),
        _recency_factor(db, opportunity),
    ]
    score = sum(f.points for f in breakdown)
    return ConfidenceScore(score=score, breakdown=breakdown)


def score_opportunity(db: Session, opportunity: Opportunity) -> Opportunity:
    """Compute the Confidence Score and persist it onto the Opportunity —
    same persist-after-compute convention as ai_service.enrich_opportunity_
    with_ai. Never touches financial fields (margin/roi/net_profit stay
    exactly as pricing_engine.py computed them)."""
    confidence = compute_confidence(db, opportunity)
    opportunity.confidence_score = confidence.score
    opportunity.confidence_breakdown = confidence.to_json()
    db.add(opportunity)
    db.commit()
    db.refresh(opportunity)
    return opportunity


@dataclass(frozen=True, slots=True)
class RecalibrationReport:
    """Read-only diagnostic: are higher confidence scores actually
    correlating with real sales? Never mutates the weight constants above
    — that remains a deliberate, versioned code change (Phase 7)."""

    sold_count: int
    expired_count: int
    avg_score_sold: float | None
    avg_score_expired: float | None

    @property
    def directionally_correct(self) -> bool | None:
        """True if SOLD opportunities scored higher on average than
        EXPIRED ones — None when there isn't enough real data yet."""
        if self.avg_score_sold is None or self.avg_score_expired is None:
            return None
        return self.avg_score_sold > self.avg_score_expired


def recalibrate_weights(db: Session) -> RecalibrationReport:
    """Compare confidence_score_at_detection between opportunities that
    actually sold vs. expired, using real analytics_events. This is the
    diagnostic input a future Phase 7 job uses to deliberately adjust the
    MAX_*_POINTS weights above — it reports, it does not auto-adjust."""

    def _avg_score(event_type: AnalyticsEventType) -> tuple[int, float | None]:
        rows = (
            db.query(AnalyticsEvent.confidence_score_at_detection)
            .filter(
                AnalyticsEvent.event_type == event_type,
                AnalyticsEvent.confidence_score_at_detection.isnot(None),
            )
            .all()
        )
        scores = [r[0] for r in rows]
        if not scores:
            return 0, None
        return len(scores), sum(scores) / len(scores)

    sold_count, avg_sold = _avg_score(AnalyticsEventType.SOLD)
    expired_count, avg_expired = _avg_score(AnalyticsEventType.EXPIRED)
    return RecalibrationReport(
        sold_count=sold_count,
        expired_count=expired_count,
        avg_score_sold=avg_sold,
        avg_score_expired=avg_expired,
    )
