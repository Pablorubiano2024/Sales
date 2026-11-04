"""Slack alerts for buyers' unanswered questions.

A question answered fast converts; one left waiting is a lost sale. Each
run (the stock-check workflow, every 15 min) posts every new UNANSWERED
question and re-posts it every RESEND_EVERY while MercadoLibre still lists
it as unanswered. Answering it on MercadoLibre is what stops the
reminders, no Slack reaction needed.

A Slack failure is logged and never raised, same as sale_alerts.
"""

from __future__ import annotations

import json as jsonlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.time import utcnow
from backend.app.models.marketplace import MarketplaceProduct
from backend.app.models.order import QuestionAlert
from backend.app.services.sale_alerts import SlackClient

RESEND_EVERY = timedelta(hours=1)
ANSWER_URL = "https://www.mercadolibre.com.co/preguntas/vendedor"


@dataclass
class QuestionRun:
    sent: int = 0
    answered: int = 0
    waiting: int = 0


def _item_name(db: Session, item_id: str) -> str:
    listing = db.query(MarketplaceProduct).filter_by(external_id=item_id).first()
    return listing.product.name if listing is not None else item_id


def question_text(db: Session, question: dict[str, Any], reminder: int) -> str:
    title = (
        "❓ *Pregunta nueva*"
        if reminder == 0
        else f"🔔 *Recordatorio {reminder}: pregunta sin responder*"
    )
    item_id = str(question.get("item_id") or "")
    asked = str(question.get("date_created") or "")[:16].replace("T", " ")
    return "\n".join(
        [
            title,
            f"*{_item_name(db, item_id)}* ({item_id})",
            f"> {question.get('text') or ''}",
            f"Hecha: {asked}",
            f"Responder: {ANSWER_URL}",
        ]
    )


def run_question_alerts(
    db: Session,
    slack: SlackClient,
    channel: str,
    unanswered: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> QuestionRun:
    now = now or utcnow()
    result = QuestionRun()
    open_ids = {str(q["id"]) for q in unanswered}

    for alert in db.query(QuestionAlert).filter(QuestionAlert.answered_at.is_(None)):
        if alert.question_id not in open_ids:
            alert.answered_at = now
            result.answered += 1
    db.commit()

    for question in unanswered:
        question_id = str(question["id"])
        existing = db.query(QuestionAlert).filter_by(question_id=question_id).first()
        if existing is not None:
            alert = existing
        else:
            alert = QuestionAlert(
                question_id=question_id, item_id=str(question.get("item_id") or "")
            )
            db.add(alert)
        alert.answered_at = None
        if alert.last_sent_at is not None and now - alert.last_sent_at < RESEND_EVERY:
            result.waiting += 1
            db.commit()
            continue
        sent_ts: list[str] = jsonlib.loads(alert.message_ts or "[]")
        ts = slack.post(channel, question_text(db, question, reminder=len(sent_ts)))
        if ts is None:
            db.commit()
            continue
        alert.message_ts = jsonlib.dumps([*sent_ts, ts])
        alert.last_sent_at = now
        db.commit()
        result.sent += 1
    return result
