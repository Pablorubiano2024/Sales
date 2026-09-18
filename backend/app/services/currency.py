"""Currency conversion at the discovery boundary.

`pricing_engine` stays currency-agnostic by design (see its module
docstring) — it just does math on whatever numbers it's given. But sources
like CJdropshipping report prices in USD, while this platform's thresholds
(`min_roi`, `min_net_profit`) and marketplace (MercadoLibre Colombia) are
COP. Comparing raw USD numbers against COP thresholds silently produces
meaningless results (a $12 USD profit looks like $12 COP, far below any
real threshold) rather than an error, so conversion has to happen before
a buy/sell price reaches the pricing engine — here, in the discovery job.

The rate is a single configurable value (`Settings.usd_to_cop_rate`), not a
live FX API call: USD/COP moves a few percent over weeks, not minutes, so a
manually-updated rate is accurate enough for arbitrage decisions and avoids
adding a third-party dependency (with its own downtime/rate-limit risk) to
every discovery run. Check the official TRM (Banco de la República,
https://www.banrep.gov.co) periodically and update `USD_TO_COP_RATE` in
your `.env` if it has drifted.
"""

from __future__ import annotations

from decimal import Decimal

from backend.app.core.config import Settings

TWOPLACES = Decimal("0.01")


def convert_to_cop(amount: Decimal, currency: str, settings: Settings) -> Decimal:
    """Convert `amount` in `currency` to COP.

    COP passes through unchanged. Raises ValueError for any other
    currency without a configured rate, rather than silently treating it
    as COP.
    """
    normalized = currency.upper()
    if normalized == "COP":
        return amount
    if normalized == "USD":
        return (amount * settings.usd_to_cop_rate).quantize(TWOPLACES)
    raise ValueError(
        f"No hay tasa de cambio configurada para la moneda {currency!r} — "
        "agrega una en backend/app/services/currency.py antes de usar esta fuente."
    )
