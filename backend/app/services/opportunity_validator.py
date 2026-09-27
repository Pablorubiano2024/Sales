"""Opportunity Validator — the pre-publish gate the user asked for
("Antes de recomendar una publicación validar automáticamente..."). Pure,
deterministic rule checks over data this codebase already computes real
values for (margin, ROI from pricing_engine.py; live stock from the
source adapters, same pattern publish_approved_opportunities.py already
uses). Two of the requested rules — `score >= 90` (Confidence Engine) and
`seller_count <= 15` (Market Gap Scanner) — depend on features not built
yet; rather than invent a value, those checks report `passed=None`
("not applicable yet") until their real data source exists, and never
silently count toward `overall_passed`. Same for "reputación mínima del
proveedor": there's no real reputation data source for a retail supplier
(Falabella/Homecenter/Imusa/Jumbo aren't individual marketplace sellers
with a reputation score) — always reported as not applicable, per the
request's own "si aplica".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.models.market_gap import MarketGapSnapshot
from backend.app.models.opportunity import Opportunity

MIN_MARGIN = Decimal("0.20")
MIN_CONFIDENCE_SCORE = 90
MAX_SELLER_COUNT = 15
# A live price more than this far from the Opportunity's stored buy_price
# is treated as "price changed" — a small tolerance absorbs real rounding/
# currency-conversion noise rather than flagging every negligible drift.
PRICE_CHANGE_TOLERANCE = Decimal("0.02")


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    name: str
    # None = not evaluated (the real data source doesn't exist yet /
    # doesn't apply to this source) — never treated as a pass or a fail.
    passed: bool | None
    detail: str


@dataclass(frozen=True, slots=True)
class ValidationResult:
    checks: list[ValidationCheck] = field(default_factory=list)

    @property
    def overall_passed(self) -> bool:
        """True only when every check that was actually evaluated passed.
        A check still pending its real data source (`passed=None`) does
        NOT block validation — it's surfaced, not silently assumed."""
        return all(c.passed is not False for c in self.checks)

    @property
    def failed_checks(self) -> list[ValidationCheck]:
        return [c for c in self.checks if c.passed is False]


def _check_margin(opportunity: Opportunity) -> ValidationCheck:
    passed = opportunity.margin >= MIN_MARGIN
    return ValidationCheck(
        name="margin",
        passed=passed,
        detail=f"margin={opportunity.margin:.2%} (mínimo {MIN_MARGIN:.0%})",
    )


def _check_confidence_score(opportunity: Opportunity) -> ValidationCheck:
    if opportunity.confidence_score is None:
        return ValidationCheck(
            name="score",
            passed=None,
            detail="Confidence Engine aún no calculado para esta oportunidad",
        )
    passed = opportunity.confidence_score >= MIN_CONFIDENCE_SCORE
    return ValidationCheck(
        name="score",
        passed=passed,
        detail=f"score={opportunity.confidence_score} (mínimo {MIN_CONFIDENCE_SCORE})",
    )


def get_latest_market_gap_snapshot(db: Session, opportunity_id: str) -> MarketGapSnapshot | None:
    """Most recent Buy Box snapshot for an Opportunity, or None until the
    Market Gap Scanner (Phase 4) has captured one. Shared with
    confidence_engine.py so both read this the same way."""
    return (
        db.query(MarketGapSnapshot)
        .filter_by(opportunity_id=opportunity_id)
        .order_by(MarketGapSnapshot.captured_at.desc())
        .first()
    )


def _check_seller_count(db: Session, opportunity: Opportunity) -> ValidationCheck:
    latest = get_latest_market_gap_snapshot(db, opportunity.id)
    if latest is None:
        return ValidationCheck(
            name="seller_count",
            passed=None,
            detail="Sin snapshot real de Market Gap Scanner todavía",
        )
    passed = latest.seller_count <= MAX_SELLER_COUNT
    return ValidationCheck(
        name="seller_count",
        passed=passed,
        detail=f"seller_count={latest.seller_count} (máximo {MAX_SELLER_COUNT})",
    )


def _check_stock(live_stock_available: bool | None) -> ValidationCheck:
    if live_stock_available is None:
        return ValidationCheck(
            name="stock", passed=None, detail="No se consultó el stock real de la fuente"
        )
    return ValidationCheck(
        name="stock",
        passed=live_stock_available,
        detail="disponible" if live_stock_available else "sin stock en la fuente",
    )


def _check_price_unchanged(
    opportunity: Opportunity, live_price_cop: Decimal | None
) -> ValidationCheck:
    if live_price_cop is None:
        return ValidationCheck(
            name="price_unchanged", passed=None, detail="No se consultó el precio real de la fuente"
        )
    if opportunity.buy_price == 0:
        return ValidationCheck(
            name="price_unchanged", passed=None, detail="buy_price original es 0, no comparable"
        )
    drift = abs(live_price_cop - opportunity.buy_price) / opportunity.buy_price
    passed = drift <= PRICE_CHANGE_TOLERANCE
    return ValidationCheck(
        name="price_unchanged",
        passed=passed,
        detail=f"precio original={opportunity.buy_price} real={live_price_cop} (drift {drift:.2%})",
    )


def _check_supplier_reputation() -> ValidationCheck:
    return ValidationCheck(
        name="supplier_reputation",
        passed=None,
        detail="No aplica: los proveedores actuales (retail) no tienen un score de reputación real",
    )


def validate_opportunity(
    db: Session,
    opportunity: Opportunity,
    *,
    live_stock_available: bool | None = None,
    live_price_cop: Decimal | None = None,
) -> ValidationResult:
    """Run every real, currently-buildable pre-publish check for one
    Opportunity. Callers that already fetched live source data (e.g.
    publish_approved_opportunities.py, which calls the source adapter
    before this) should pass `live_stock_available`/`live_price_cop`
    straight through rather than re-fetching."""
    checks = [
        _check_margin(opportunity),
        _check_confidence_score(opportunity),
        _check_seller_count(db, opportunity),
        _check_stock(live_stock_available),
        _check_price_unchanged(opportunity, live_price_cop),
        _check_supplier_reputation(),
    ]
    return ValidationResult(checks=checks)
