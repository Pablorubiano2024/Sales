"""Tests for the MercadoLibre adapter's real OAuth authenticate() flow,
using httpx.MockTransport so no real network calls happen. Response shapes
match the request/response fields documented in MercadoLibre's own OAuth
docs (see mercadolibre.py's module docstring for the verified source)."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.orm import Session

from backend.app.core.time import utcnow
from backend.app.integrations import mercadolibre as ml_module
from backend.app.integrations.mercadolibre import MercadoLibreAdapter
from backend.app.models.marketplace import Marketplace
from backend.app.models.marketplace_credential import MarketplaceCredential

FAKE_SETTINGS = SimpleNamespace(
    ml_client_id="APP-1", ml_client_secret="secret", ml_redirect_uri="https://x/callback"
)


def _make_credential(db: Session, *, expires_in: timedelta) -> MarketplaceCredential:
    marketplace = Marketplace(name="MercadoLibre Colombia", country="CO")
    db.add(marketplace)
    db.commit()
    db.refresh(marketplace)

    credential = MarketplaceCredential(
        marketplace_id=marketplace.id,
        access_token="old-access-token",
        refresh_token="old-refresh-token",
        expires_at=utcnow() + expires_in,
        external_user_id="123456",
        scope="read write offline_access",
    )
    db.add(credential)
    db.commit()
    db.refresh(credential)
    return credential


def test_authenticate_without_stored_credential_returns_false_no_network_call(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ml_module, "get_settings", lambda: FAKE_SETTINGS)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not make any HTTP call when there's no credential")

    with MercadoLibreAdapter(db_session, transport=httpx.MockTransport(handler)) as adapter:
        assert adapter.authenticate() is False


def test_authenticate_with_valid_token_verifies_live_and_succeeds(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ml_module, "get_settings", lambda: FAKE_SETTINGS)
    _make_credential(db_session, expires_in=timedelta(hours=5))

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/users/me"
        assert request.headers["authorization"] == "Bearer old-access-token"
        return httpx.Response(200, json={"id": 123456, "nickname": "TEST"})

    with MercadoLibreAdapter(db_session, transport=httpx.MockTransport(handler)) as adapter:
        assert adapter.authenticate() is True


def test_authenticate_refreshes_near_expiry_token_and_persists_new_tokens(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ml_module, "get_settings", lambda: FAKE_SETTINGS)
    credential = _make_credential(db_session, expires_in=timedelta(minutes=1))

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/oauth/token":
            body = request.read().decode()
            assert "grant_type=refresh_token" in body
            assert "old-refresh-token" in body
            return httpx.Response(
                200,
                json={
                    "access_token": "new-access-token",
                    "token_type": "bearer",
                    "expires_in": 21600,
                    "scope": "read write offline_access",
                    "user_id": 123456,
                    "refresh_token": "new-refresh-token",
                },
            )
        assert request.url.path == "/users/me"
        assert request.headers["authorization"] == "Bearer new-access-token"
        return httpx.Response(200, json={"id": 123456})

    with MercadoLibreAdapter(db_session, transport=httpx.MockTransport(handler)) as adapter:
        assert adapter.authenticate() is True

    assert calls == ["/oauth/token", "/users/me"]
    db_session.refresh(credential)
    assert credential.access_token == "new-access-token"
    # The refresh_token is single-use — the new one must replace the old one.
    assert credential.refresh_token == "new-refresh-token"


def test_authenticate_returns_false_when_refresh_fails(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ml_module, "get_settings", lambda: FAKE_SETTINGS)
    _make_credential(db_session, expires_in=timedelta(minutes=1))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    with MercadoLibreAdapter(db_session, transport=httpx.MockTransport(handler)) as adapter:
        assert adapter.authenticate() is False


def test_authenticate_returns_false_when_verification_call_fails(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ml_module, "get_settings", lambda: FAKE_SETTINGS)
    _make_credential(db_session, expires_in=timedelta(hours=5))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "invalid token"})

    with MercadoLibreAdapter(db_session, transport=httpx.MockTransport(handler)) as adapter:
        assert adapter.authenticate() is False
