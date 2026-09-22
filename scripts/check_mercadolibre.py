"""Checks the real MercadoLibre OAuth connection end to end.

Requires `ML_CLIENT_ID` / `ML_CLIENT_SECRET` / `ML_REDIRECT_URI` in your
`.env` (see backend/app/integrations/mercadolibre.py for how to get them).

If no account has been connected yet, prints the URL to visit (your
backend's `/api/marketplaces/mercadolibre/authorize`) to run through the
real OAuth flow in a browser. Once connected, running this again calls
`MercadoLibreAdapter.authenticate()`, which refreshes the token if needed
and verifies it against the real `/users/me` endpoint — the same
"confirm it live" step used when building the CJdropshipping adapter.

Usage:
    python scripts/check_mercadolibre.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core.config import get_settings  # noqa: E402
from backend.app.core.database import SessionLocal, init_db  # noqa: E402
from backend.app.integrations.mercadolibre import MercadoLibreAdapter  # noqa: E402


def main() -> None:
    settings = get_settings()
    if not settings.ml_client_id or not settings.ml_client_secret or not settings.ml_redirect_uri:
        sys.exit(
            "ML_CLIENT_ID / ML_CLIENT_SECRET / ML_REDIRECT_URI no están configurados en tu .env "
            "— ver backend/app/integrations/mercadolibre.py para cómo obtenerlos."
        )

    init_db()
    db = SessionLocal()
    try:
        with MercadoLibreAdapter(db) as adapter:
            if adapter.authenticate():
                print("Conectado y verificado en vivo contra la API real de MercadoLibre.")
            else:
                backend_url = settings.ml_redirect_uri.rsplit("/api/", 1)[0]
                print(
                    "No hay una cuenta conectada todavía (o el token dejó de ser válido).\n"
                    f"Visita esto en tu navegador para autorizar: "
                    f"{backend_url}/api/marketplaces/mercadolibre/authorize"
                )
    finally:
        db.close()


if __name__ == "__main__":
    main()
