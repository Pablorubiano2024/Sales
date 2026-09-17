"""Deterministic profit/ROI/margin calculations.

This module is the single source of truth for arbitrage math. It must
never depend on AI/Claude and must be fully deterministic and unit-tested.
All monetary math is done with Decimal to avoid floating point drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

TWOPLACES = Decimal("0.01")
FOURPLACES = Decimal("0.0001")

Money = Decimal | int | float | str


def _to_decimal(value: Money) -> Decimal:
    """Coerce a numeric input into a Decimal safely (via str to avoid
    binary float artifacts, e.g. Decimal(0.1) issues)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _quantize(value: Decimal, places: Decimal = TWOPLACES) -> Decimal:
    return value.quantize(places, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class ProfitBreakdown:
    """Result of a full profitability calculation."""

    buy_price: Decimal
    sell_price: Decimal
    marketplace_fee: Decimal
    shipping_cost: Decimal
    tax_cost: Decimal
    payment_cost: Decimal
    other_cost: Decimal

    gross_profit: Decimal
    net_profit: Decimal
    roi: Decimal
    margin: Decimal


def calculate_gross_profit(sell_price: Money, buy_price: Money) -> Decimal:
    """Gross profit = sell_price - buy_price (before marketplace/operating costs)."""
    return _quantize(_to_decimal(sell_price) - _to_decimal(buy_price))


def calculate_total_costs(
    marketplace_fee: Money = 0,
    shipping_cost: Money = 0,
    tax_cost: Money = 0,
    payment_cost: Money = 0,
    other_cost: Money = 0,
) -> Decimal:
    total = (
        _to_decimal(marketplace_fee)
        + _to_decimal(shipping_cost)
        + _to_decimal(tax_cost)
        + _to_decimal(payment_cost)
        + _to_decimal(other_cost)
    )
    return _quantize(total)


def calculate_net_profit(
    sell_price: Money,
    buy_price: Money,
    marketplace_fee: Money = 0,
    shipping_cost: Money = 0,
    tax_cost: Money = 0,
    payment_cost: Money = 0,
    other_cost: Money = 0,
) -> Decimal:
    """net_profit = sell_price - buy_price - marketplace_fee - shipping_cost
    - tax_cost - payment_cost - other_cost."""
    total_costs = calculate_total_costs(
        marketplace_fee, shipping_cost, tax_cost, payment_cost, other_cost
    )
    net = _to_decimal(sell_price) - _to_decimal(buy_price) - total_costs
    return _quantize(net)


def calculate_roi(net_profit: Money, buy_price: Money) -> Decimal:
    """ROI = net_profit / buy_price. Returns 0 when buy_price is 0 to avoid
    a division-by-zero crash (an opportunity with no purchase cost has no
    meaningful ROI ratio)."""
    buy = _to_decimal(buy_price)
    if buy == 0:
        return Decimal("0")
    return _quantize(_to_decimal(net_profit) / buy, FOURPLACES)


def calculate_margin(net_profit: Money, sell_price: Money) -> Decimal:
    """Margin = net_profit / sell_price. Returns 0 when sell_price is 0."""
    sell = _to_decimal(sell_price)
    if sell == 0:
        return Decimal("0")
    return _quantize(_to_decimal(net_profit) / sell, FOURPLACES)


def calculate_profit_breakdown(
    buy_price: Money,
    sell_price: Money,
    marketplace_fee: Money = 0,
    shipping_cost: Money = 0,
    tax_cost: Money = 0,
    payment_cost: Money = 0,
    other_cost: Money = 0,
) -> ProfitBreakdown:
    """Compute the full deterministic profitability breakdown for an opportunity."""
    buy = _to_decimal(buy_price)
    sell = _to_decimal(sell_price)
    fee = _to_decimal(marketplace_fee)
    shipping = _to_decimal(shipping_cost)
    tax = _to_decimal(tax_cost)
    payment = _to_decimal(payment_cost)
    other = _to_decimal(other_cost)

    gross_profit = calculate_gross_profit(sell, buy)
    net_profit = calculate_net_profit(sell, buy, fee, shipping, tax, payment, other)
    roi = calculate_roi(net_profit, buy)
    margin = calculate_margin(net_profit, sell)

    return ProfitBreakdown(
        buy_price=_quantize(buy),
        sell_price=_quantize(sell),
        marketplace_fee=_quantize(fee),
        shipping_cost=_quantize(shipping),
        tax_cost=_quantize(tax),
        payment_cost=_quantize(payment),
        other_cost=_quantize(other),
        gross_profit=gross_profit,
        net_profit=net_profit,
        roi=roi,
        margin=margin,
    )
