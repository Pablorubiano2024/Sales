"""Tests for the API-key auth dependency (backend/app/core/security.py)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.core import security


def test_api_key_is_valid_disabled_when_not_configured() -> None:
    assert security.api_key_is_valid(None, None) is True
    assert security.api_key_is_valid("anything", None) is True
    assert security.api_key_is_valid("anything", "") is True


def test_api_key_is_valid_requires_match_when_configured() -> None:
    assert security.api_key_is_valid("secret", "secret") is True
    assert security.api_key_is_valid("wrong", "secret") is False
    assert security.api_key_is_valid(None, "secret") is False


@pytest.fixture()
def configured_auth(monkeypatch: pytest.MonkeyPatch) -> str:
    token = "secret123"
    monkeypatch.setattr(security, "get_settings", lambda: SimpleNamespace(api_auth_token=token))
    return token


def test_api_endpoint_rejects_missing_or_wrong_key(
    client: TestClient, configured_auth: str
) -> None:
    response = client.get("/api/products")
    assert response.status_code == 401

    response = client.get("/api/products", headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


def test_api_endpoint_accepts_correct_key(client: TestClient, configured_auth: str) -> None:
    response = client.get("/api/products", headers={"X-API-Key": configured_auth})
    assert response.status_code == 200


def test_health_endpoint_never_requires_a_key(client: TestClient, configured_auth: str) -> None:
    response = client.get("/health")
    assert response.status_code == 200
