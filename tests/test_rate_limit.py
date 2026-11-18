"""Tests for rate_limit.RetryOn429Transport."""

from __future__ import annotations

import httpx

from backend.app.integrations.rate_limit import RETRIES, RetryOn429Transport


def _client(responses: list[httpx.Response], waits: list[float]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    transport = RetryOn429Transport(httpx.MockTransport(handler), sleep=waits.append)
    return httpx.Client(base_url="https://api.mercadolibre.com", transport=transport)


def test_retries_a_rate_limit_then_returns_the_answer() -> None:
    waits: list[float] = []
    responses = [httpx.Response(429), httpx.Response(429), httpx.Response(200, json={"ok": 1})]
    with _client(responses, waits) as client:
        assert client.get("/products/search").json() == {"ok": 1}
    assert waits == [2.0, 4.0]


def test_honors_retry_after() -> None:
    waits: list[float] = []
    responses = [httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200)]
    with _client(responses, waits) as client:
        assert client.get("/x").status_code == 200
    assert waits == [7.0]


def test_gives_up_after_the_last_retry() -> None:
    waits: list[float] = []
    responses = [httpx.Response(429) for _ in range(RETRIES + 1)]
    with _client(responses, waits) as client:
        assert client.get("/x").status_code == 429
    assert len(waits) == RETRIES


def test_other_errors_are_not_retried() -> None:
    waits: list[float] = []
    with _client([httpx.Response(403)], waits) as client:
        assert client.get("/x").status_code == 403
    assert waits == []
