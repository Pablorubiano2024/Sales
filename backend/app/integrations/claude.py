"""Anthropic Claude integration.

Wraps the official `anthropic` SDK to produce a structured, Pydantic-validated
enrichment analysis for an arbitrage opportunity. This module never performs
the underlying financial calculations (see services/pricing_engine.py) — it
only enriches an already-computed opportunity with AI-derived scores and
qualitative reasoning.

If no API key is configured, or the API call fails for any reason, callers
get `None` back instead of an exception — the rest of the application must
keep working without AI enrichment.
"""

from __future__ import annotations

from typing import Any

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.schemas.opportunity import AIOpportunityAnalysis

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You are an e-commerce arbitrage analyst for the Colombian market "
    "(marketplaces such as MercadoLibre). Given a candidate product "
    "opportunity with its already-computed financial figures, assess "
    "product-match confidence, demand, competition and risk. Do not "
    "recompute or second-guess the provided financial numbers — only "
    "assess the qualitative factors. Respond with concise, actionable "
    "reasoning aimed at a small operator deciding whether to list this "
    "product."
)


class ClaudeService:
    """Thin, fail-soft wrapper around the Anthropic Messages API."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: Any | None = None

    def _get_client(self) -> Any | None:
        if not self._settings.anthropic_api_key:
            return None
        if self._client is None:
            import anthropic  # imported lazily so the app runs without the package configured

            self._client = anthropic.Anthropic(api_key=self._settings.anthropic_api_key)
        return self._client

    def is_configured(self) -> bool:
        return bool(self._settings.anthropic_api_key)

    def analyze_opportunity(
        self, opportunity_input: dict[str, Any]
    ) -> AIOpportunityAnalysis | None:
        """Ask Claude to enrich an opportunity with qualitative scores.

        `opportunity_input` should contain only what's needed for the
        assessment (product name, category, prices, ROI, margin,
        competition/stock hints) — never unnecessary sensitive data.
        Returns None (never raises) if Claude is not configured or the
        call fails for any reason.
        """
        client = self._get_client()
        if client is None:
            logger.info("Claude analysis skipped: ANTHROPIC_API_KEY not configured.")
            return None

        try:
            import anthropic

            response = client.messages.parse(
                model=self._settings.anthropic_model,
                max_tokens=2048,
                system=_SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Assess this arbitrage opportunity and return the "
                            f"structured analysis:\n\n{opportunity_input}"
                        ),
                    }
                ],
                output_format=AIOpportunityAnalysis,
            )
            return response.parsed_output
        except anthropic.APIError as exc:
            logger.warning("Claude API call failed: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001 - AI enrichment must never crash the app
            logger.warning("Unexpected error during Claude analysis: %s", exc)
            return None


_claude_service: ClaudeService | None = None


def get_claude_service() -> ClaudeService:
    global _claude_service
    if _claude_service is None:
        _claude_service = ClaudeService()
    return _claude_service
