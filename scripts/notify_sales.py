"""Imports new MercadoLibre sales and alerts Slack until each one gets a ✅
(see backend/app/services/sale_alerts.py). Runs inside the stock-check
workflow. Needs SLACK_BOT_TOKEN and SLACK_SALES_CHANNEL; without them it
only imports the sales.

Usage:
    python scripts/notify_sales.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.config import get_settings  # noqa: E402
from backend.app.core.database import SessionLocal, init_db  # noqa: E402
from backend.app.integrations.mercadolibre import MercadoLibreAdapter  # noqa: E402
from backend.app.jobs.order_sync import run_order_sync  # noqa: E402
from backend.app.services.sale_alerts import SlackClient, run_sale_alerts  # noqa: E402


def main() -> None:
    init_db()
    settings = get_settings()
    db = SessionLocal()
    try:
        with MercadoLibreAdapter(db) as ml:
            if not ml.authenticate():
                sys.exit("No hay una cuenta de MercadoLibre conectada/válida.")
            print(f"Ventas nuevas importadas: {run_order_sync(db, ml)}")

            if not settings.slack_bot_token or not settings.slack_sales_channel:
                print("SLACK_BOT_TOKEN / SLACK_SALES_CHANNEL no configurados — sin alertas.")
                return
            slack = SlackClient(settings.slack_bot_token)
            try:
                run = run_sale_alerts(
                    db, slack, settings.slack_sales_channel, deadline_for=ml.get_dispatch_deadline
                )
            finally:
                slack.close()
            print(
                f"Alertas enviadas: {run.sent}  Confirmadas ✅: {run.acknowledged}  "
                f"Esperando: {run.waiting}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
