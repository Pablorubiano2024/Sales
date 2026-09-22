"""Tests for the MercadoLibre adapter's real OAuth authenticate() flow,
using httpx.MockTransport so no real network calls happen. Response shapes
match the request/response fields documented in MercadoLibre's own OAuth
docs (see mercadolibre.py's module docstring for the verified source)."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
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


def test_create_listing_requires_category_id(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ml_module, "get_settings", lambda: FAKE_SETTINGS)
    with MercadoLibreAdapter(
        db_session, transport=httpx.MockTransport(lambda r: httpx.Response(200))
    ) as adapter:
        adapter._authenticated = True  # noqa: SLF001 — bypass auth for this unit test
        adapter._access_token = "tok"  # noqa: SLF001
        with pytest.raises(ValueError, match="category_id"):
            adapter.create_listing("prod-1", "Item de Prueba", Decimal("10000"), "COP")


def test_create_listing_requires_authentication_first(db_session: Session) -> None:
    with MercadoLibreAdapter(db_session) as adapter:
        with pytest.raises(RuntimeError, match="authenticate"):
            adapter.create_listing(
                "prod-1", "Item de Prueba", Decimal("10000"), "COP", category_id="MCO412060"
            )


def test_create_listing_posts_verified_payload_and_parses_response(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ml_module, "get_settings", lambda: FAKE_SETTINGS)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/items"
        assert request.headers["authorization"] == "Bearer tok"
        payload = json.loads(request.read())
        assert payload["category_id"] == "MCO412060"
        assert payload["listing_type_id"] == "free"
        assert payload["currency_id"] == "COP"
        assert {"id": "BRAND", "value_name": "Generic"} in payload["attributes"]
        return httpx.Response(
            201,
            json={
                "id": "MCO123456789",
                "title": payload["title"],
                "price": payload["price"],
                "currency_id": "COP",
                "status": "active",
                "permalink": "https://articulo.mercadolibre.com.co/MCO-123456789",
            },
        )

    with MercadoLibreAdapter(db_session, transport=httpx.MockTransport(handler)) as adapter:
        adapter._authenticated = True  # noqa: SLF001
        adapter._access_token = "tok"  # noqa: SLF001
        result = adapter.create_listing(
            "prod-1",
            "Item de Prueba - Por favor, NO OFERTAR",
            Decimal("5000"),
            "COP",
            category_id="MCO412060",
        )

    assert result.external_id == "MCO123456789"
    assert result.status == "active"
    assert result.url == "https://articulo.mercadolibre.com.co/MCO-123456789"


def test_update_listing_puts_fields_and_returns_updated_item(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ml_module, "get_settings", lambda: FAKE_SETTINGS)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url.path == "/items/MCO123456789"
        assert json.loads(request.read()) == {"status": "paused"}
        return httpx.Response(
            200,
            json={
                "id": "MCO123456789",
                "title": "Item de Prueba - Por favor, NO OFERTAR",
                "price": 5000,
                "currency_id": "COP",
                "status": "paused",
                "permalink": "https://articulo.mercadolibre.com.co/MCO-123456789",
            },
        )

    with MercadoLibreAdapter(db_session, transport=httpx.MockTransport(handler)) as adapter:
        adapter._authenticated = True  # noqa: SLF001
        adapter._access_token = "tok"  # noqa: SLF001
        result = adapter.update_listing("MCO123456789", status="paused")

    assert result.status == "paused"
