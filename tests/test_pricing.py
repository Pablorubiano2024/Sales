"""Tests for the deterministic pricing engine (no external dependencies)."""

from __future__ import annotations

from decimal import Decimal

from backend.app.services.pricing_engine import (
    calculate_gross_profit,
    calculate_margin,
    calculate_net_profit,
    calculate_profit_breakdown,
    calculate_roi,
)


def test_gross_profit_basic() -> None:
    assert calculate_gross_profit(sell_price=100000, buy_price=40000) == Decimal("60000.00")


def test_net_profit_subtracts_all_costs() -> None:
    net = calculate_net_profit(
        sell_price=100000,
        buy_price=40000,
        marketplace_fee=8000,
        shipping_cost=5000,
        tax_cost=2000,
        payment_cost=1000,
        other_cost=500,
    )
    assert net == Decimal("43500.00")


def test_roi_calculation() -> None:
    roi = calculate_roi(net_profit=20000, buy_price=40000)
    assert roi == Decimal("0.5000")


def test_roi_zero_buy_price_does_not_crash() -> None:
    assert calculate_roi(net_profit=1000, buy_price=0) == Decimal("0")


def test_margin_calculation() -> None:
    margin = calculate_margin(net_profit=25000, sell_price=100000)
    assert margin == Decimal("0.2500")


def test_margin_zero_sell_price_does_not_crash() -> None:
    assert calculate_margin(net_profit=1000, sell_price=0) == Decimal("0")


def test_profit_breakdown_end_to_end() -> None:
    breakdown = calculate_profit_breakdown(
        buy_price=Decimal("45000"),
        sell_price=Decimal("120000"),
        marketplace_fee=Decimal("12000"),
        shipping_cost=Decimal("8000"),
        payment_cost=Decimal("3000"),
    )
    assert breakdown.gross_profit == Decimal("75000.00")
    assert breakdown.net_profit == Decimal("52000.00")
    assert breakdown.roi == Decimal("1.1556")
    assert breakdown.margin == Decimal("0.4333")


def test_profit_breakdown_negative_profit_is_not_clamped() -> None:
    """Losses must surface as negative numbers, not be hidden."""
    breakdown = calculate_profit_breakdown(
        buy_price=Decimal("32000"),
        sell_price=Decimal("38000"),
        marketplace_fee=Decimal("6000"),
        shipping_cost=Decimal("6000"),
        payment_cost=Decimal("1500"),
    )
    assert breakdown.net_profit == Decimal("-7500.00")
    assert breakdown.roi < 0


def test_decimal_inputs_avoid_float_drift() -> None:
    # 0.1 + 0.2 famously != 0.3 in binary float; Decimal-via-str avoids that.
    net = calculate_net_profit(sell_price="100.3", buy_price="100.2")
    assert net == Decimal("0.10")
