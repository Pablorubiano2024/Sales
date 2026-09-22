"""Tests for the /api/marketplaces/mercadolibre/authorize + /callback
routes — the OAuth endpoints that MUST work without an X-API-Key, since
they're hit by browser redirects from MercadoLibre, not our own frontend."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.api import mercadolibre_oauth

FAKE_SETTINGS = SimpleNamespace(
    ml_client_id="APP-1", ml_client_secret="secret", ml_redirect_uri="https://x/callback"
)


def test_authorize_without_config_returns_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        mercadolibre_oauth,
        "get_settings",
        lambda: SimpleNamespace(ml_client_id=None, ml_client_secret=None, ml_redirect_uri=None),
    )
    response = client.get("/api/marketplaces/mercadolibre/authorize", follow_redirects=False)
    assert response.status_code == 503


def test_authorize_redirects_to_mercadolibre_with_correct_params(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mercadolibre_oauth, "get_settings", lambda: FAKE_SETTINGS)
    response = client.get("/api/marketplaces/mercadolibre/authorize", follow_redirects=False)
    assert response.status_code == 307
    location = response.headers["location"]
    assert location.startswith("https://auth.mercadolibre.com.co/authorization?")
    assert "response_type=code" in location
    assert "client_id=APP-1" in location
    assert "redirect_uri=https://x/callback" in location


def test_callback_exchanges_code_and_stores_credential(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mercadolibre_oauth, "get_settings", lambda: FAKE_SETTINGS)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/oauth/token"
        body = request.read().decode()
        assert "grant_type=authorization_code" in body
        assert "code=auth-code-123" in body
        return httpx.Response(
            200,
            json={
                "access_token": "acc-tok",
                "token_type": "bearer",
                "expires_in": 21600,
                "scope": "read write offline_access",
                "user_id": 999,
                "refresh_token": "ref-tok",
            },
        )

    original_client = httpx.Client

    def fake_client(*args: object, **kwargs: object) -> httpx.Client:
        return original_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(mercadolibre_oauth.httpx, "Client", fake_client)

    response = client.get("/api/marketplaces/mercadolibre/callback?code=auth-code-123")
    assert response.status_code == 200
    assert "conectada" in response.text.lower()

    status_response = client.get("/api/marketplaces/mercadolibre/status")
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["connected"] is True
    assert body["external_user_id"] == "999"


def test_callback_returns_502_when_token_exchange_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mercadolibre_oauth, "get_settings", lambda: FAKE_SETTINGS)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    original_client = httpx.Client

    def fake_client(*args: object, **kwargs: object) -> httpx.Client:
        return original_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(mercadolibre_oauth.httpx, "Client", fake_client)

    response = client.get("/api/marketplaces/mercadolibre/callback?code=bad-code")
    assert response.status_code == 502


def test_status_endpoint_requires_api_key_when_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "backend.app.core.security.get_settings",
        lambda: SimpleNamespace(api_auth_token="secret123"),
    )
    response = client.get("/api/marketplaces/mercadolibre/status")
    assert response.status_code == 401
