"""Capital Simulator (Autopilot Phase 7) — the user gives capital, a max
number of daily purchases, and a minimum margin; the system projects
potential sales, capital rotation, monthly profit, monthly ROI, and time
to double the capital.

Deterministic and grounded in real data wherever it exists:
  - avg_buy_price / avg_margin / avg_net_profit_per_sale come from real
    APPROVED Opportunities that clear `min_margin` — never a guessed
    number.
  - avg_time_to_sale_days comes from real AnalyticsEvent rows
    (event_type=SOLD, time_to_sale_minutes) when at least one exists.
    Right now this account has zero completed real sales, so there is no
    real value yet — the simulator uses a documented, clearly-labeled
    default assumption in that case (`time_to_sale_is_real_data=False` on
    the result) rather than inventing a false-precision number silently.
    Once Phase 5's Order Router completes real sales and Phase 7's
    analytics wiring records them, this automatically switches to real
    data with no further changes needed here.

Capital rotation model: capital deployed today isn't available again
until the average sale completes (avg_time_to_sale_days later). The
steady-state sustainable purchase RATE is therefore
(capital / avg_buy_price) / avg_time_to_sale_days — the user's
`max_daily_purchases` can only lower that, never raise it beyond what the
capital can actually sustain.

`daily_purchases` is that continuous rate (e.g. 0.86), not floored to a
whole number — checked live 2026-09-28 against real production data: with
real capital that sustains fewer than 1 whole unit per calendar day (a
completely normal case for smaller capital against a multi-day rotation),
flooring to an integer produced a false "$0 monthly profit" even though
the same capital genuinely supports real periodic purchases (e.g. ~6
units bought together, then a ~7-day wait). Flooring only the *purchase
count* while keeping profit continuous double-penalizes slow-rotation
scenarios, so profit/ROI are derived from the continuous rate throughout.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from backend.app.models.analytics import AnalyticsEvent, AnalyticsEventType
from backend.app.models.opportunity import Opportunity, OpportunityStatus

# Used only when there isn't yet a single real completed sale to compute
# a real average time-to-sale from — documented, never silently blended
# with real data.
DEFAULT_TIME_TO_SALE_DAYS = Decimal("7")
DAYS_PER_MONTH = Decimal("30")
TWOPLACES = Decimal("0.01")
FOURPLACES = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class SimulationError:
    reason: str


@dataclass(frozen=True, slots=True)
class CapitalSimulationResult:
    qualifying_opportunities: int
    avg_buy_price: Decimal
    avg_margin: Decimal
    avg_net_profit_per_sale: Decimal
    avg_time_to_sale_days: Decimal
    time_to_sale_is_real_data: bool

    daily_purchases: Decimal
    daily_capital_deployed: Decimal
    daily_profit: Decimal
    monthly_profit: Decimal
    monthly_roi: Decimal
    capital_rotations_per_month: Decimal
    days_to_double_capital: Decimal | None


def _real_avg_time_to_sale_days(db: Session) -> Decimal | None:
    rows = (
        db.query(AnalyticsEvent.time_to_sale_minutes)
        .filter(
            AnalyticsEvent.event_type == AnalyticsEventType.SOLD,
            AnalyticsEvent.time_to_sale_minutes.isnot(None),
        )
        .all()
    )
    minutes = [r[0] for r in rows]
    if not minutes:
        return None
    avg_minutes = sum(minutes) / len(minutes)
    # FOURPLACES, not TWOPLACES — a very fast real rotation (well under a
    # day) would otherwise round to exactly 0.00 and incorrectly zero out
    # the sustainable-purchases math below via the `> 0` guards.
    return (Decimal(avg_minutes) / Decimal("1440")).quantize(FOURPLACES, rounding=ROUND_HALF_UP)


def run_capital_simulation(
    db: Session, *, capital: Decimal, max_daily_purchases: int, min_margin: Decimal
) -> CapitalSimulationResult | SimulationError:
    if capital <= 0:
        return SimulationError("El capital debe ser mayor a 0")
    if max_daily_purchases <= 0:
        return SimulationError("El máximo de compras diarias debe ser mayor a 0")

    qualifying = (
        db.query(Opportunity)
        .filter(
            Opportunity.status == OpportunityStatus.APPROVED,
            Opportunity.margin >= min_margin,
            Opportunity.buy_price > 0,
        )
        .all()
    )
    if not qualifying:
        return SimulationError(
            f"No hay oportunidades aprobadas reales con margen >= {min_margin:.0%}"
        )

    count = len(qualifying)
    avg_buy_price = (sum((o.buy_price for o in qualifying), Decimal("0")) / count).quantize(
        TWOPLACES, rounding=ROUND_HALF_UP
    )
    avg_margin = (sum((o.margin for o in qualifying), Decimal("0")) / count).quantize(
        FOURPLACES, rounding=ROUND_HALF_UP
    )
    avg_net_profit_per_sale = (
        sum((o.net_profit for o in qualifying), Decimal("0")) / count
    ).quantize(TWOPLACES, rounding=ROUND_HALF_UP)

    real_time_to_sale = _real_avg_time_to_sale_days(db)
    avg_time_to_sale_days = (
        real_time_to_sale if real_time_to_sale is not None else (DEFAULT_TIME_TO_SALE_DAYS)
    )

    # Units that can be "in flight" (purchased, awaiting sale) at once:
    # bounded by capital, and separately by what the user is willing to
    # buy per day sustained over one full rotation cycle.
    total_units_capacity = int((capital / avg_buy_price).to_integral_value(rounding="ROUND_FLOOR"))
    max_units_from_daily_cap = Decimal(max_daily_purchases) * avg_time_to_sale_days
    units_in_flight = min(Decimal(total_units_capacity), max_units_from_daily_cap)

    daily_purchases = (
        (units_in_flight / avg_time_to_sale_days).quantize(FOURPLACES, rounding=ROUND_HALF_UP)
        if avg_time_to_sale_days > 0
        else Decimal("0")
    )

    daily_capital_deployed = (daily_purchases * avg_buy_price).quantize(
        TWOPLACES, rounding=ROUND_HALF_UP
    )
    daily_profit = (daily_purchases * avg_net_profit_per_sale).quantize(
        TWOPLACES, rounding=ROUND_HALF_UP
    )
    monthly_profit = (daily_profit * DAYS_PER_MONTH).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
    monthly_roi = (
        (monthly_profit / capital).quantize(FOURPLACES, rounding=ROUND_HALF_UP)
        if capital > 0
        else Decimal("0")
    )
    capital_rotations_per_month = (
        (DAYS_PER_MONTH / avg_time_to_sale_days).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        if avg_time_to_sale_days > 0
        else Decimal("0")
    )
    days_to_double_capital = (
        (capital / daily_profit).quantize(TWOPLACES, rounding=ROUND_HALF_UP)
        if daily_profit > 0
        else None
    )

    return CapitalSimulationResult(
        qualifying_opportunities=count,
        avg_buy_price=avg_buy_price,
        avg_margin=avg_margin,
        avg_net_profit_per_sale=avg_net_profit_per_sale,
        avg_time_to_sale_days=avg_time_to_sale_days,
        time_to_sale_is_real_data=real_time_to_sale is not None,
        daily_purchases=daily_purchases,
        daily_capital_deployed=daily_capital_deployed,
        daily_profit=daily_profit,
        monthly_profit=monthly_profit,
        monthly_roi=monthly_roi,
        capital_rotations_per_month=capital_rotations_per_month,
        days_to_double_capital=days_to_double_capital,
    )
