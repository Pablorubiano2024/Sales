"""Tests for sale_alerts.py — Slack mocked with httpx.MockTransport."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from backend.app.models.marketplace import Marketplace
from backend.app.models.opportunity import Opportunity
from backend.app.models.order import CustomerShippingStatus, Order, SaleAlert
from backend.app.models.product import Product
from backend.app.models.source import Source, SourceType
from backend.app.services.sale_alerts import SlackClient, alert_text, run_sale_alerts


class _FakeSlack:
    def __init__(self) -> None:
        self.posts: list[str] = []
        self.acked: set[str] = set()
        self.reactions: dict[str, str] = {}
        self.replied: set[str] = set()
        self.channel_messages: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/chat.postMessage":
            self.posts.append(json.loads(request.content)["text"])
            return httpx.Response(200, json={"ok": True, "ts": f"ts{len(self.posts)}"})
        if request.url.path == "/api/conversations.history":
            return httpx.Response(200, json={"ok": True, "messages": self.channel_messages})
        ts = dict(httpx.QueryParams(request.content.decode()))["timestamp"]
        message: dict = {"reactions": []}
        if ts in self.acked:
            message["reactions"] = [{"name": "white_check_mark"}]
        if ts in self.reactions:
            message["reactions"] = [{"name": self.reactions[ts]}]
        if ts in self.replied:
            message["reply_count"] = 1
        return httpx.Response(200, json={"ok": True, "message": message})


def _order(db: Session) -> Order:
    product = Product(sku="ALERT-1", name="Audífonos Red Bull")
    db.add(product)
    db.commit()
    order = Order(
        marketplace_order_id="2000019111671518",
        product_id=product.id,
        selling_price=Decimal("92900"),
        supplier_price=Decimal("49900"),
        expected_profit=Decimal("20100"),
    )
    db.add(order)
    db.commit()
    return order


def test_alert_repeats_until_acknowledged(db_session: Session) -> None:
    _order(db_session)
    fake = _FakeSlack()
    slack = SlackClient("xoxb-test", transport=httpx.MockTransport(fake.handler))
    t0 = datetime(2026, 10, 22, 12, 0)

    first = run_sale_alerts(db_session, slack, "C1", deadline_for=lambda _: "2026-10-22T23:59:59")
    assert first.sent == 1
    assert "¡Nueva venta!" in fake.posts[0] and "2026-10-22 23:59" in fake.posts[0]
    alert = db_session.query(SaleAlert).one()
    alert.last_sent_at = t0
    db_session.commit()

    # stock-check runs every 15 minutes; reminders go out hourly.
    assert run_sale_alerts(db_session, slack, "C1", now=t0 + timedelta(minutes=16)).waiting == 1
    assert run_sale_alerts(db_session, slack, "C1", now=t0 + timedelta(minutes=61)).sent == 1
    assert "Recordatorio 1" in fake.posts[1]

    fake.acked.add("ts1")  # ✅ on the first message
    assert run_sale_alerts(db_session, slack, "C1", now=t0 + timedelta(hours=2)).acknowledged == 1
    assert run_sale_alerts(db_session, slack, "C1", now=t0 + timedelta(hours=3)).sent == 0
    assert len(fake.posts) == 2


def test_slack_failure_is_not_raised(db_session: Session) -> None:
    _order(db_session)
    slack = SlackClient(
        "xoxb-test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"ok": False})),
    )
    assert run_sale_alerts(db_session, slack, "C1").sent == 0


def test_alert_reminds_to_pay_with_the_falabella_card(db_session: Session) -> None:
    order = _order(db_session)
    falabella = Source(name="Falabella Colombia", source_type=SourceType.API)
    marketplace = Marketplace(name="MercadoLibre Colombia")
    db_session.add_all([falabella, marketplace])
    db_session.commit()
    opportunity = Opportunity(
        product_id=order.product_id,
        source_id=falabella.id,
        marketplace_id=marketplace.id,
        buy_price=Decimal("899900"),
        sell_price=Decimal("1461900"),
    )
    db_session.add(opportunity)
    db_session.commit()

    without_source = alert_text(db_session, order, None, reminder=0)
    order.opportunity_id = opportunity.id
    with_falabella = alert_text(db_session, order, None, reminder=0)

    assert "tarjeta Falabella" not in without_source
    assert "tarjeta Falabella" in with_falabella


def test_no_alert_once_the_sale_has_shipped(db_session: Session) -> None:
    order = _order(db_session)
    order.customer_shipping_status = CustomerShippingStatus.SHIPPED
    db_session.commit()
    fake = _FakeSlack()
    slack = SlackClient("xoxb-test", transport=httpx.MockTransport(fake.handler))
    assert run_sale_alerts(db_session, slack, "C1").sent == 0
    assert fake.posts == []


def test_any_reaction_acknowledges(db_session: Session) -> None:
    _order(db_session)
    fake = _FakeSlack()
    slack = SlackClient("xoxb-test", transport=httpx.MockTransport(fake.handler))
    run_sale_alerts(db_session, slack, "C1")
    fake.reactions["ts1"] = "+1"
    assert run_sale_alerts(db_session, slack, "C1", now=datetime(2030, 1, 1)).acknowledged == 1


def test_a_thread_reply_acknowledges(db_session: Session) -> None:
    _order(db_session)
    fake = _FakeSlack()
    slack = SlackClient("xoxb-test", transport=httpx.MockTransport(fake.handler))
    run_sale_alerts(db_session, slack, "C1")
    fake.replied.add("ts1")
    assert run_sale_alerts(db_session, slack, "C1", now=datetime(2030, 1, 1)).acknowledged == 1


def test_a_person_messaging_the_channel_acknowledges(db_session: Session) -> None:
    _order(db_session)
    fake = _FakeSlack()
    slack = SlackClient("xoxb-test", transport=httpx.MockTransport(fake.handler))
    run_sale_alerts(db_session, slack, "C1")
    fake.channel_messages = [{"ts": "ts9", "bot_id": "B1", "user": "U0"}]
    assert run_sale_alerts(db_session, slack, "C1", now=datetime(2030, 1, 1)).acknowledged == 0
    fake.channel_messages.append({"ts": "ts10", "user": "U1", "text": ":white_check_mark:"})
    assert run_sale_alerts(db_session, slack, "C1", now=datetime(2031, 1, 1)).acknowledged == 1
