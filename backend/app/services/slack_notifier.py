"""Slack notifier (Autopilot Phase 6) — same mechanism already proven in
the "Jobs" project's app/slack_notifier.py: a real Slack Incoming Webhook
(api.slack.com/messaging/webhooks), POSTed a `{"text": ...}` JSON payload,
Slack replies with the literal body "ok" on success. Uses httpx (already
a core dependency here) instead of Jobs' urllib — same contract, more
consistent with the rest of this codebase's HTTP calls.

No OpenClaw CLI fallback (Jobs' local-dev path) — this project has no
such tool installed; when SLACK_WEBHOOK_URL isn't configured, alerts are
simply skipped (logged, never queued or silently swallowed as "sent").
"""

from __future__ import annotations

import httpx

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 15.0


def send_slack(text: str) -> bool:
    """POSTs `text` to the configured Slack Incoming Webhook. Returns
    False (logged, not raised) when no webhook is configured or the real
    call fails — a Slack outage must never break the caller's own job."""
    settings = get_settings()
    if not settings.slack_webhook_url:
        logger.info("SLACK_WEBHOOK_URL no configurado — alerta omitida: %s", text[:80])
        return False

    try:
        response = httpx.post(
            settings.slack_webhook_url, json={"text": text}, timeout=DEFAULT_TIMEOUT
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Envío a Slack falló: %s", exc)
        return False

    if response.text.strip() != "ok":
        logger.warning("Slack webhook respondió inesperado: %r", response.text)
        return False
    return True
