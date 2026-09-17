"""Minimal API-key authentication for /api/* routes.

Deliberately simple for the MVP: a single shared secret (`API_AUTH_TOKEN`)
checked against an `X-API-Key` header. No users, roles, or sessions — this
exists to stop the API from being wide open once it's deployed somewhere
reachable beyond localhost, not to be a full auth system. If a future phase
needs per-user auth, replace this dependency without touching route logic.

When `API_AUTH_TOKEN` is unset, auth is disabled (local/dev convenience) —
`/health` is always open regardless, since it has no dependency on this.
"""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from backend.app.core.config import get_settings


def api_key_is_valid(provided: str | None, configured: str | None) -> bool:
    """Pure check, kept separate from the FastAPI dependency for easy testing."""
    if not configured:
        return True
    return provided == configured


async def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    settings = get_settings()
    if not api_key_is_valid(x_api_key, settings.api_auth_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
