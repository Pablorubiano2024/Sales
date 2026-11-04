"""Tests for question_alerts.py — Slack mocked with httpx.MockTransport."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from backend.app.models.marketplace import Marketplace, MarketplaceProduct
from backend.app.models.order import QuestionAlert
from backend.app.models.product import Product
from backend.app.services.question_alerts import run_question_alerts
from backend.app.services.sale_alerts import SlackClient

NOW = datetime(2026, 11, 4, 12, 0)
QUESTION = {
    "id": 13000000001,
    "item_id": "MCO2236126911",
    "text": "¿Tiene garantía?",
    "date_created": "2026-11-04T11:58:00.000-04:00",
}


def _slack(posts: list[str]) -> SlackClient:
    def handler(request: httpx.Request) -> httpx.Response:
        posts.append(json.loads(request.content)["text"])
        return httpx.Response(200, json={"ok": True, "ts": f"ts{len(posts)}"})

    return SlackClient("token", transport=httpx.MockTransport(handler))


def _listing(db: Session) -> None:
    product = Product(sku="Q-1", name="Freidora Imusa 7.5L")
    marketplace = Marketplace(name="MercadoLibre Colombia")
    db.add_all([product, marketplace])
    db.commit()
    db.add(
        MarketplaceProduct(
            marketplace_id=marketplace.id,
            product_id=product.id,
            external_id="MCO2236126911",
            selling_price=Decimal("622900"),
        )
    )
    db.commit()


def test_new_question_is_posted_with_its_listing(db_session: Session) -> None:
    _listing(db_session)
    posts: list[str] = []

    run = run_question_alerts(db_session, _slack(posts), "C1", [QUESTION], now=NOW)

    assert run.sent == 1
    assert "Pregunta nueva" in posts[0]
    assert "Freidora Imusa 7.5L" in posts[0]
    assert "¿Tiene garantía?" in posts[0]


def test_unanswered_question_is_reminded_only_after_an_hour(db_session: Session) -> None:
    posts: list[str] = []
    slack = _slack(posts)

    run_question_alerts(db_session, slack, "C1", [QUESTION], now=NOW)
    soon = run_question_alerts(db_session, slack, "C1", [QUESTION], now=NOW + timedelta(minutes=15))
    later = run_question_alerts(db_session, slack, "C1", [QUESTION], now=NOW + timedelta(hours=1))

    assert (soon.sent, soon.waiting) == (0, 1)
    assert later.sent == 1
    assert "Recordatorio 1" in posts[1]
    assert "MCO2236126911" in posts[1]


def test_answered_question_stops_alerting(db_session: Session) -> None:
    posts: list[str] = []
    slack = _slack(posts)
    run_question_alerts(db_session, slack, "C1", [QUESTION], now=NOW)

    run = run_question_alerts(db_session, slack, "C1", [], now=NOW + timedelta(hours=2))

    assert (run.sent, run.answered) == (0, 1)
    alert = db_session.query(QuestionAlert).one()
    assert alert.answered_at == NOW + timedelta(hours=2)
    assert len(posts) == 1
