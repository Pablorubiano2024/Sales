"""Settings page: view current profitability thresholds and config status."""

from __future__ import annotations

import api_client
import streamlit as st

st.set_page_config(page_title="Settings", page_icon="⚙️", layout="wide")
st.title("⚙️ Settings")

try:
    settings = api_client.get_settings()
except api_client.ApiError as exc:
    st.error(str(exc))
    st.stop()

col1, col2, col3 = st.columns(3)
col1.metric("Minimum ROI", f"{settings['min_roi']:.0%}")
col2.metric("Minimum Net Profit", f"${settings['min_net_profit']:,.0f}")
col3.metric("Maximum Risk Score", f"{settings['max_risk_score']:.2f}")

st.divider()
st.write(f"**Environment:** {settings['app_env']}")
st.write(f"**Default currency:** {settings['default_currency']}")

if settings["claude_configured"]:
    st.success("Claude AI enrichment is configured (ANTHROPIC_API_KEY set).")
else:
    st.warning(
        "Claude AI enrichment is NOT configured. Set ANTHROPIC_API_KEY in your "
        ".env to enable AI-assisted opportunity analysis. The platform works "
        "without it — financial calculations are deterministic and do not "
        "depend on AI."
    )

st.caption(
    "These thresholds are configured via environment variables (MIN_ROI, "
    "MIN_NET_PROFIT, MAX_RISK_SCORE) — see .env.example. Changing them here "
    "is not yet implemented; edit .env and restart the backend."
)
