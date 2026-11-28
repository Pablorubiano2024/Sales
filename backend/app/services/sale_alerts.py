"""Persistent Slack alerts for real sales.

The first sale (2026-10-22) was only noticed by chance. Each run (the
stock-check workflow) posts every open sale to Slack and keeps re-posting
it every RESEND_EVERY until someone reacts (any emoji) or replies in the
thread of any of its messages — the "Enterado" button. Any reaction, not
only ✅: on 2026-11-28 the owner's ✅ never registered (reactions.get
kept returning none, no error) and the alert re-posted 56 times — the
✅ was most likely sent as a channel message, so a person's message in
the channel after the alert also counts (conversations.history, scope
channels:history; without it Slack answers missing_scope, logged).
A real Slack button needs a public endpoint that
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

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.core.time import utcnow
from backend.app.models.opportunity import Opportunity
from backend.app.models.order import CustomerShippingStatus, Order, OrderStatus, SaleAlert
from backend.app.models.source import Source, SourceProduct

logger = get_logger(__name__)

SLACK_API = "https://slack.com/api"
# Was 15 minutes, matching the old stock-check cadence of a few runs a
# day. Since stock-check runs every 15 minutes for real (2026-11-25) that
# meant 4 messages an hour; hourly is enough to not miss a sale.
RESEND_EVERY = timedelta(hours=1)
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
        """Any reaction on the message, or any reply in its thread
        (reactions.get returns the message with its reply_count, so no
        extra scope is needed)."""
        data = self._call("reactions.get", data={"channel": channel, "timestamp": ts})
        message = (data or {}).get("message") or {}
        reactions = message.get("reactions") or []
        replies = int(message.get("reply_count") or 0)
        if reactions or replies:
            logger.info(
                "Slack %s acknowledged: reactions=%s replies=%s",
                ts,
                [r.get("name") for r in reactions],
                replies,
            )
        return bool(reactions or replies)

    def has_human_message_after(self, channel: str, ts: str) -> bool:
        """A message from a person (not a bot) posted in the channel after ts."""
        data = self._call(
            "conversations.history", data={"channel": channel, "oldest": ts, "limit": 50}
        )
        for message in (data or {}).get("messages") or []:
            if message.get("user") and not message.get("bot_id") and not message.get("subtype"):
                logger.info("Slack %s acknowledged by a channel message at %s", ts, message["ts"])
                return True
        return False


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


# Sources priced at their "precio CMR" (falabella_source.py).
CMR_SOURCES = {"Falabella Colombia", "Homecenter Colombia"}


def _pays_with_cmr(db: Session, order: Order) -> bool:
    opportunity = db.get(Opportunity, order.opportunity_id) if order.opportunity_id else None
    source = db.get(Source, opportunity.source_id) if opportunity else None
    return bool(get_settings().falabella_cmr_card and source and source.name in CMR_SOURCES)


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
    if _pays_with_cmr(db, order):
        lines.append("💳 Paga con tu tarjeta Falabella: el costo asume el precio CMR.")
    if order.marketplace_order_id:
        lines.append(f"Venta: {ORDER_URL.format(order_id=order.marketplace_order_id)}")
    lines.append(
        "Reacciona con ✅, responde en el hilo o escribe en el canal "
        "para dejar de recibir recordatorios."
    )
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
    # Only sales still waiting to be dispatched: once MercadoLibre reports
    # one shipped (order_sync), there's nothing left to remind about.
    orders = (
        db.query(Order)
        .filter(
            Order.status != OrderStatus.CANCELLED,
            Order.customer_shipping_status == CustomerShippingStatus.NOT_SHIPPED,
        )
        .all()
    )
    for order in orders:
        alert = db.query(SaleAlert).filter_by(order_id=order.id).first()
        if alert is None:
            alert = SaleAlert(order_id=order.id)
            db.add(alert)
        if alert.acknowledged_at is not None:
            continue
        sent_ts: list[str] = jsonlib.loads(alert.message_ts or "[]")
        if any(slack.is_acknowledged(channel, ts) for ts in sent_ts) or (
            sent_ts and slack.has_human_message_after(channel, sent_ts[0])
        ):
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
