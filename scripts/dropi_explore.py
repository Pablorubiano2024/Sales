"""One-off exploration script for Dropi's real API (api.dropi.co).

Confirmed live and official (2026-09-17): api.dropi.co/docs serves a real
OpenAPI 3.0 spec (contact: soporteti@dropi.co) documenting only 8
endpoints — none for the product catalog. Probing confirmed
`POST /api/products` and `POST /integrations/products` exist (401
Unauthorized, not 404) but their request schema isn't publicly documented.

This script logs in with YOUR OWN Dropi credentials (read from your local
.env — never typed into chat, never sent anywhere but api.dropi.co) and
then sends deliberately empty/invalid bodies to the products endpoints.
Laravel APIs typically respond to invalid input with a validation-error
JSON body that names the actual required fields — that's what we're
after here, not real data.

Run locally:
    DROPI_EMAIL=you@example.com DROPI_PASSWORD=yourpassword DROPI_WHITE_BRAND_ID= \
        poetry run python scripts/dropi_explore.py

Paste the PRINTED OUTPUT back (it contains no password) — that's what's
needed to build the real adapter.
"""

from __future__ import annotations

import json
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://api.dropi.co"


def _print_response(label: str, response: httpx.Response) -> None:
    print(f"\n--- {label} ---")
    print("status:", response.status_code)
    try:
        print(json.dumps(response.json(), indent=2, ensure_ascii=False)[:2000])
    except ValueError:
        print(response.text[:500])


def main() -> None:
    email = os.environ.get("DROPI_EMAIL")
    password = os.environ.get("DROPI_PASSWORD")
    white_brand_id = os.environ.get("DROPI_WHITE_BRAND_ID", "")

    if not email or not password:
        sys.exit("Set DROPI_EMAIL and DROPI_PASSWORD (env vars or .env) before running this.")

    with httpx.Client(base_url=BASE_URL, timeout=15.0) as client:
        login_response = client.post(
            "/integrations/login",
            json={"email": email, "password": password, "white_brand_id": white_brand_id},
        )
        _print_response("POST /integrations/login", login_response)

        if login_response.status_code != 200:
            print("\nLogin failed — stopping here. Check credentials/white_brand_id.")
            return

        token = login_response.json().get("token")
        headers = {"Authorization": f"Bearer {token}"}

        whoiam_response = client.post("/integrations/whoiam", headers=headers)
        _print_response("POST /integrations/whoiam", whoiam_response)

        # Deliberately empty bodies: we want the validation-error shape,
        # not real data, to learn the real required fields.
        for path in ("/api/products", "/integrations/products"):
            resp = client.post(path, headers=headers, json={})
            _print_response(f"POST {path} (empty body)", resp)

        for path in ("/api/products", "/integrations/products"):
            resp = client.get(path, headers=headers)
            _print_response(f"GET {path}", resp)

        categories_response = client.get("/api/categories", headers=headers)
        _print_response("GET /api/categories", categories_response)


if __name__ == "__main__":
    main()
