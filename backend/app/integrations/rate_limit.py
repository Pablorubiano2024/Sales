"""Retry MercadoLibre's rate limit instead of reading it as "no data".

A 429 ("local_rate_limited") on a catalog search used to come back as "no
identical product", so the item was skipped as having no competitor
prices (2026-11-18 dry run: ~9 of 100 "sin precio real" were 429s). This
transport waits and retries, honoring Retry-After when MercadoLibre sends
one."""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from backend.app.core.logging import get_logger

logger = get_logger(__name__)

RETRIES = 4
FIRST_WAIT_SECONDS = 2.0
MAX_WAIT_SECONDS = 30.0


class RetryOn429Transport(httpx.BaseTransport):
    def __init__(
        self,
        inner: httpx.BaseTransport | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._inner = inner or httpx.HTTPTransport()
        self._sleep = sleep

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        wait = FIRST_WAIT_SECONDS
        for attempt in range(RETRIES + 1):
            response = self._inner.handle_request(request)
            if response.status_code != 429 or attempt == RETRIES:
                return response
            response.read()
            response.close()
            delay = _retry_after(response) or wait
            logger.info("429 on %s, retrying in %.0fs", request.url.path, delay)
            self._sleep(min(delay, MAX_WAIT_SECONDS))
            wait *= 2
        raise AssertionError("unreachable")

    def close(self) -> None:
        self._inner.close()


def _retry_after(response: httpx.Response) -> float | None:
    try:
        return float(response.headers["Retry-After"])
    except (KeyError, ValueError):
        return None
