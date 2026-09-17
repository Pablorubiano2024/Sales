"""Thin HTTP client for the Streamlit frontend to talk to the FastAPI backend.

All business logic lives in the backend; this module only makes HTTP calls
and returns parsed JSON. Keeps Streamlit as a pure presentation layer.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from dotenv import load_dotenv

# Streamlit doesn't load .env on its own (unlike the backend, via
# pydantic-settings) — load it here so BACKEND_API_URL / API_AUTH_TOKEN
# behave the same way for both processes.
load_dotenv()

API_BASE_URL = os.environ.get("BACKEND_API_URL", "http://127.0.0.1:8000")
API_AUTH_TOKEN = os.environ.get("API_AUTH_TOKEN")


class ApiError(RuntimeError):
    pass


def _request(method: str, path: str, **kwargs: Any) -> Any:
    url = f"{API_BASE_URL}{path}"
    headers = kwargs.pop("headers", None) or {}
    if API_AUTH_TOKEN:
        headers["X-API-Key"] = API_AUTH_TOKEN
    try:
        response = httpx.request(method, url, timeout=10.0, headers=headers, **kwargs)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.json().get("detail", str(exc)) if exc.response.content else str(exc)
        raise ApiError(f"{method} {path} failed: {detail}") from exc
    except httpx.ConnectError as exc:
        raise ApiError(
            f"Could not reach backend at {API_BASE_URL}. Is the FastAPI server running?"
        ) from exc


def get_health() -> dict:
    return _request("GET", "/health")


def get_settings() -> dict:
    return _request("GET", "/api/settings")


def get_products(**params: Any) -> list[dict]:
    return _request("GET", "/api/products", params=params)


def create_product(payload: dict) -> dict:
    return _request("POST", "/api/products", json=payload)


def get_opportunities(**params: Any) -> list[dict]:
    return _request("GET", "/api/opportunities", params=params)


def get_opportunity(opportunity_id: str) -> dict:
    return _request("GET", f"/api/opportunities/{opportunity_id}")


def analyze_opportunity(payload: dict) -> dict:
    return _request("POST", "/api/opportunities/analyze", json=payload)


def get_orders(**params: Any) -> list[dict]:
    return _request("GET", "/api/orders", params=params)


def get_marketplaces() -> list[dict]:
    return _request("GET", "/api/marketplaces")
