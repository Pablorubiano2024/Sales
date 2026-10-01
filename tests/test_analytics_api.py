"""API test for GET /api/analytics/summary (Autopilot Phase 7)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_summary_with_no_data(client: TestClient) -> None:
    response = client.get("/api/analytics/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["detected_count"] == 0
    assert body["sold_count"] == 0
    assert body["confidence_recalibration"]["directionally_correct"] is None


def test_today_with_no_data(client: TestClient) -> None:
    response = client.get("/api/analytics/today")
    assert response.status_code == 200
    body = response.json()
    assert body["detected_today"] == 0
    assert body["published_today"] == 0
    assert body["sold_today"] == 0
    assert body["market_gap_events_today"] == 0


def test_funnel_with_no_data(client: TestClient) -> None:
    response = client.get("/api/analytics/funnel")
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "found": 0,
        "validated": 0,
        "published": 0,
        "sold": 0,
        "expired": 0,
        "cancelled": 0,
    }
