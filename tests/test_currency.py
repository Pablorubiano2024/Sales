"""Tests for USD -> COP conversion at the discovery boundary."""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.app.core.config import Settings
from backend.app.services.currency import convert_to_cop


def test_cop_passes_through_unchanged() -> None:
    settings = Settings(usd_to_cop_rate=Decimal("4000"))
    assert convert_to_cop(Decimal("50000"), "COP", settings) == Decimal("50000")


def test_usd_converted_using_configured_rate() -> None:
    settings = Settings(usd_to_cop_rate=Decimal("4000"))
    assert convert_to_cop(Decimal("10"), "USD", settings) == Decimal("40000.00")


def test_currency_code_is_case_insensitive() -> None:
    settings = Settings(usd_to_cop_rate=Decimal("4000"))
    assert convert_to_cop(Decimal("10"), "usd", settings) == Decimal("40000.00")


def test_unsupported_currency_raises() -> None:
    settings = Settings(usd_to_cop_rate=Decimal("4000"))
    with pytest.raises(ValueError, match="EUR"):
        convert_to_cop(Decimal("10"), "EUR", settings)
