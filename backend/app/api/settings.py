"""Settings API endpoint. Exposes current (non-sensitive) configuration
thresholds so the frontend can display/reference them without duplicating
logic. Never exposes secrets such as the Anthropic API key."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from backend.app.core.config import get_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsRead(BaseModel):
    app_env: str
    default_currency: str
    min_roi: float
    min_net_profit: float
    max_risk_score: float
    claude_configured: bool


@router.get("", response_model=SettingsRead)
def get_app_settings() -> SettingsRead:
    settings = get_settings()
    return SettingsRead(
        app_env=settings.app_env,
        default_currency=settings.default_currency,
        min_roi=float(settings.min_roi),
        min_net_profit=float(settings.min_net_profit),
        max_risk_score=settings.max_risk_score,
        claude_configured=bool(settings.anthropic_api_key),
    )
