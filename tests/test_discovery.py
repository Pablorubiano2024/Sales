"""Tests for the discovery job's currency conversion wiring: a USD-priced
source must produce COP-denominated opportunities, not raw USD numbers
compared against COP thresholds."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.integrations.base import SourceAdapter, SourceProductInfo
from backend.app.jobs import discovery as discovery_module
from backend.app.jobs.discovery import run_discovery
from backend.app.models.marketplace import Marketplace
from backend.app.models.opportunity import Opportunity
from backend.app.models.source import Source, SourceType


class _FakeUsdAdapter(SourceAdapter):
    """Returns one fixed USD-priced product, regardless of query."""

    def search_products(self, query: str, limit: int = 20) -> list[SourceProductInfo]:
        return [
            SourceProductInfo(
                external_id="usd-1",
                name="Wireless Earbuds",
                price=Decimal("10.00"),
                currency="USD",
                stock_available=True,
                url="https://example.com/usd-1",
            )
        ]

    def get_product(self, external_id: str) -> SourceProductInfo | None:
        raise NotImplementedError

    def get_price(self, external_id: str) -> Decimal | None:
        raise NotImplementedError

    def get_stock(self, external_id: str) -> bool:
        raise NotImplementedError

    def get_product_url(self, external_id: str) -> str | None:
        raise NotImplementedError


@pytest.fixture()
def _fixed_rate_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = Settings(usd_to_cop_rate=Decimal("4000"))
    monkeypatch.setattr(discovery_module, "get_settings", lambda: settings)
    return settings


def test_usd_source_price_is_converted_to_cop_before_evaluation(
    db_session: Session, _fixed_rate_settings: Settings
) -> None:
    source = Source(name="Fake USD Source", source_type=SourceType.API)
    marketplace = Marketplace(name="Test Marketplace")
    db_session.add_all([source, marketplace])
    db_session.commit()
    db_session.refresh(source)
    db_session.refresh(marketplace)

    opportunity_ids = run_discovery(
        db_session,
        source,
        _FakeUsdAdapter(),
        marketplace.id,
        queries=["earbuds"],
    )

    assert len(opportunity_ids) == 1
    opportunity = db_session.get(Opportunity, opportunity_ids[0])
    assert opportunity is not None
    # $10 USD * 4000 COP/USD = 40,000 COP — not 10.
    assert opportunity.buy_price == Decimal("40000.00")


def test_marketplace_fee_and_shipping_are_deducted(
    db_session: Session, _fixed_rate_settings: Settings
) -> None:
    """A discovered opportunity must reflect real marketplace commission and
    shipping, not just the raw buy price — see Settings.marketplace_commission_pct
    / shipping_cost_cop and their history in config.py."""
    source = Source(name="Fake USD Source", source_type=SourceType.API)
    marketplace = Marketplace(name="Test Marketplace")
    db_session.add_all([source, marketplace])
    db_session.commit()
    db_session.refresh(source)
    db_session.refresh(marketplace)

    opportunity_ids = run_discovery(
        db_session, source, _FakeUsdAdapter(), marketplace.id, queries=["earbuds"]
    )
    opportunity = db_session.get(Opportunity, opportunity_ids[0])
    assert opportunity is not None

    # sell = 40,000 * 1.8 = 72,000; fee = 72,000 * 0.15 (default) = 10,800
    assert opportunity.marketplace_fee == Decimal("10800.00")
    assert opportunity.shipping_cost == _fixed_rate_settings.shipping_cost_cop
    # Confirms these costs actually reduce net_profit rather than being
    # computed-but-ignored.
    assert opportunity.net_profit == (
        opportunity.sell_price
        - opportunity.buy_price
        - opportunity.marketplace_fee
        - opportunity.shipping_cost
    )
