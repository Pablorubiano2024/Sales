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
