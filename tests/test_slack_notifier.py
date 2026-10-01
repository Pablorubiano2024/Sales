"""Tests for slack_notifier.py (Autopilot Phase 6) using httpx.MockTransport
— no real network calls."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from backend.app.services import slack_notifier


def _fake_response(status_code: int, text: str) -> httpx.Response:
    return httpx.Response(
        status_code,
        text=text,
        request=httpx.Request("POST", "https://hooks.slack.com/services/FAKE"),
    )


def test_send_slack_returns_false_without_webhook_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        slack_notifier, "get_settings", lambda: SimpleNamespace(slack_webhook_url=None)
    )
    assert slack_notifier.send_slack("hola") is False


def test_send_slack_posts_text_payload_and_returns_true_on_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        slack_notifier,
        "get_settings",
        lambda: SimpleNamespace(slack_webhook_url="https://hooks.slack.com/services/FAKE"),
    )

    captured = {}

    def fake_post(url, *, json, timeout):
        captured["url"] = url
        captured["json"] = json
        return _fake_response(200, "ok")

    monkeypatch.setattr(slack_notifier.httpx, "post", fake_post)

    assert slack_notifier.send_slack("🚨 GOLD OPPORTUNITY") is True
    assert captured["url"] == "https://hooks.slack.com/services/FAKE"
    assert captured["json"] == {"text": "🚨 GOLD OPPORTUNITY"}


def test_send_slack_returns_false_on_unexpected_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        slack_notifier,
        "get_settings",
        lambda: SimpleNamespace(slack_webhook_url="https://hooks.slack.com/services/FAKE"),
    )
    monkeypatch.setattr(
        slack_notifier.httpx, "post", lambda *a, **k: _fake_response(200, "invalid_payload")
    )
    assert slack_notifier.send_slack("hola") is False


def test_send_slack_returns_false_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        slack_notifier,
        "get_settings",
        lambda: SimpleNamespace(slack_webhook_url="https://hooks.slack.com/services/FAKE"),
    )

    def fake_post(*a, **k):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(slack_notifier.httpx, "post", fake_post)
    assert slack_notifier.send_slack("hola") is False
