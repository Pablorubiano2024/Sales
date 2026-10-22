"""Persistent Slack alerts for real sales.

The first sale (2026-10-22) was only noticed by chance. Each run (the
stock-check workflow) posts every open sale to Slack and keeps re-posting
it every RESEND_EVERY until someone reacts ✅ to any of its messages —
the "Enterado" button. A real Slack button needs a public endpoint that
answers within 3s, and Render's free instance sleeps, so the reaction is
read back with reactions.get instead (bot scopes chat:write +
reactions:read).

A Slack failure is logged and never raised: alerts must not break the
stock check they run inside.
"""

from __future__ import annotations

import json as jsonlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from backend.app.core.logging import get_logger
from backend.app.core.time import utcnow
from backend.app.models.opportunity import Opportunity
from backend.app.models.order import Order, OrderStatus, SaleAlert
from backend.app.models.source import SourceProduct

logger = get_logger(__name__)

SLACK_API = "https://slack.com/api"
RESEND_EVERY = timedelta(minutes=15)
ACK_REACTIONS = {"white_check_mark", "heavy_check_mark", "ballot_box_with_check"}
ORDER_URL = "https://www.mercadolibre.com.co/ventas/{order_id}/detalle"


class SlackClient:
    def __init__(self, token: str, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(
            base_url=SLACK_API,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15.0,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _call(
        self, method: str, *, json: dict | None = None, data: dict | None = None
    ) -> dict | None:
        try:
            response = self._client.post(f"/{method}", json=json, data=data)
            body: dict = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Slack %s failed: %s", method, exc)
            return None
        if not body.get("ok"):
            logger.warning("Slack %s error: %s", method, body.get("error"))
            return None
        return body

    def post(self, channel: str, text: str) -> str | None:
        data = self._call("chat.postMessage", json={"channel": channel, "text": text})
        return data.get("ts") if data else None

    def is_acknowledged(self, channel: str, ts: str) -> bool:
        data = self._call("reactions.get", data={"channel": channel, "timestamp": ts})
        reactions = ((data or {}).get("message") or {}).get("reactions") or []
        return any(r.get("name") in ACK_REACTIONS for r in reactions)


@dataclass
class AlertRun:
    sent: int = 0
    acknowledged: int = 0
    waiting: int = 0


def _source_url(db: Session, order: Order) -> str | None:
    opportunity = db.get(Opportunity, order.opportunity_id) if order.opportunity_id else None
    if opportunity is None:
        return None
    source_product = (
        db.query(SourceProduct)
        .filter_by(source_id=opportunity.source_id, product_id=opportunity.product_id)
        .first()
    )
    return source_product.url if source_product else None


def _cop(value: object) -> str:
    return f"${value:,.0f}".replace(",", ".")


def alert_text(db: Session, order: Order, deadline: str | None, reminder: int) -> str:
    title = (
        "🛒 *¡Nueva venta!*"
        if reminder == 0
        else f"🔔 *Recordatorio {reminder}: venta sin confirmar*"
    )
    lines = [
        title,
        f"*{order.product.name}*",
        f"Venta {_cop(order.selling_price)} · compra {_cop(order.supplier_price)} · "
        f"ganancia neta ≈ {_cop(order.expected_profit)}",
    ]
    if deadline:
        lines.append(f"⏰ Entregar a Mercado Envíos antes de: {deadline[:16].replace('T', ' ')}")
    source_url = _source_url(db, order)
    if source_url:
        lines.append(f"Comprar en: {source_url}")
    if order.marketplace_order_id:
        lines.append(f"Venta: {ORDER_URL.format(order_id=order.marketplace_order_id)}")
    lines.append("Reacciona con ✅ a este mensaje para dejar de recibir recordatorios.")
    return "\n".join(lines)


def run_sale_alerts(
    db: Session,
    slack: SlackClient,
    channel: str,
    *,
    deadline_for: Callable[[str], str | None] = lambda _order_id: None,
    now: datetime | None = None,
) -> AlertRun:
    now = now or utcnow()
    result = AlertRun()
    orders = db.query(Order).filter(Order.status != OrderStatus.CANCELLED).all()
    for order in orders:
        alert = db.query(SaleAlert).filter_by(order_id=order.id).first()
        if alert is None:
            alert = SaleAlert(order_id=order.id)
            db.add(alert)
        if alert.acknowledged_at is not None:
            continue
        sent_ts: list[str] = jsonlib.loads(alert.message_ts or "[]")
        if any(slack.is_acknowledged(channel, ts) for ts in sent_ts):
            alert.acknowledged_at = now
            db.commit()
            result.acknowledged += 1
            continue
        if alert.last_sent_at is not None and now - alert.last_sent_at < RESEND_EVERY:
            result.waiting += 1
            continue
        deadline = deadline_for(order.marketplace_order_id) if order.marketplace_order_id else None
        ts = slack.post(channel, alert_text(db, order, deadline, reminder=len(sent_ts)))
        if ts is None:
            db.commit()
            continue
        alert.message_ts = jsonlib.dumps([*sent_ts, ts])
        alert.last_sent_at = now
        db.commit()
        result.sent += 1
    return result
