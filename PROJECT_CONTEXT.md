# PROJECT_CONTEXT.md

Context file for future AI coding agents working on this repository. Read this before making
architectural changes.

## PROJECT

Automated Product Arbitrage Platform (Colombia-focused, MercadoLibre as the initial target
marketplace).

## GOAL

Build a system that finds profitable products to resell without holding inventory: discover
cheap supplier products, match them to higher-priced marketplace listings, calculate real
profitability (all costs included), rank opportunities, and — eventually — automate listing
creation and order-driven supplier purchasing.

## CURRENT ARCHITECTURE

FastAPI (backend API + business logic) + Streamlit (presentation-only dashboard) + SQLAlchemy +
SQLite locally / Postgres in production via `DATABASE_URL` (Neon) + Anthropic Claude (optional
enrichment). See `README.md` for the full folder structure, setup, and the Deployment section
(Neon + Render + Streamlit Community Cloud, three separately-hosted pieces, no Docker).

**Language split:** code, comments, commit messages and this doc are in English. The Streamlit
UI text (`frontend/`) is in Spanish, per the user's request — keep new frontend strings in
Spanish and route API enum values through `frontend/i18n.py` rather than translating the API
contract itself.

## BUSINESS MODEL

Buy from the supplier only after a marketplace sale happens whenever possible. No inventory is
held or modeled. Current chain (see README for the diagram): supplier has stock → opportunity
found → listed → customer buys → order detected → user alerted → user manually buys from
supplier → supplier ships directly to customer → profit tracked.

## IMPORTANT PRINCIPLES

1. **Financial calculations are deterministic.** `backend/app/services/pricing_engine.py` and
   `opportunity_engine.py` use `Decimal` arithmetic and never call an LLM. Do not make profit/
   ROI/margin/status depend on AI output.
2. **AI enriches analysis but does not replace mathematical calculations.**
   `backend/app/services/ai_service.py` layers Claude-derived scores (demand, competition, risk,
   overall) and reasoning on top of an already-computed opportunity. If Claude is unavailable or
   errors, the app must keep working — `integrations/claude.py` returns `None` rather than
   raising.
3. **Integrations must be modular.** `backend/app/integrations/base.py` defines
   `SourceAdapter` and `MarketplaceAdapter` interfaces. New sources/marketplaces implement these
   interfaces; the arbitrage engine and API never depend on a specific integration.
4. **Never invent API endpoints.** `integrations/mercadolibre.py` is a skeleton: every method
   either raises `NotImplementedError` with a TODO or clearly no-ops, because we do not have
   verified MercadoLibre API documentation/credentials wired in yet. Do not fill in guessed
   endpoint URLs or fabricate response shapes — confirm against official docs first.
5. **Never hard-code credentials.** All secrets/config come from environment variables via
   `backend/app/core/config.py` (`pydantic-settings`, reading `.env`). `.env` is git-ignored;
   only `.env.example` is committed (with blank/placeholder values).
6. **Do not unnecessarily collect sensitive customer data.** `models/order.py` intentionally
   omits customer PII (name, address, phone, etc.) — the MVP doesn't need it. If a future phase
   requires storing customer shipping details, treat that as a deliberate, reviewed decision,
   not an incidental addition.
7. **Avoid vendor lock-in.** Keep the marketplace/source abstractions real abstractions — don't
   let MercadoLibre- or one-supplier-specific assumptions leak into `services/` or `models/`.
8. **Keep the MVP simple.** Don't add scheduling infrastructure, message queues, multi-tenant
   auth, or inventory tracking unless a phase below calls for it and the user asks.
9. **Prefer automation but preserve manual approval for risky operations.** Opportunity
   classification (REJECTED/REVIEW/PROMISING/APPROVED) is automatic; publishing to a marketplace
   and purchasing from a supplier should stay explicit user actions until a later phase
   deliberately automates them.
10. **All external integrations must fail gracefully.** A down/misconfigured Claude API, a
    missing MercadoLibre credential, or a source that returns no data must degrade the relevant
    feature, not crash the request. Follow the pattern in `integrations/claude.py` (catch, log,
    return `None`/empty, let the caller decide what to show).

## KEY MODULES (where to look)

- `backend/app/services/pricing_engine.py` — the only place profit/ROI/margin math happens.
- `backend/app/services/opportunity_engine.py` — threshold-based classification
  (`MIN_ROI`, `MIN_NET_PROFIT`, `MAX_RISK_SCORE` from Settings — never hard-code these elsewhere).
- `backend/app/services/arbitrage_engine.py` — orchestrates pricing + classification into a
  persisted `Opportunity`.
- `backend/app/integrations/base.py` — the adapter interfaces every source/marketplace
  integration must implement.
- `backend/app/integrations/mock_source.py` — fake, in-memory supplier used for dev/tests; do not
  treat as a real integration.
- `backend/app/integrations/dummyjson_source.py` — a real HTTP `SourceAdapter` (real requests,
  real error handling) against the public DummyJSON demo product API. Proves out the integration
  pattern; it is still NOT a real Colombian supplier (fictional USD prices) — see its docstring.
- `backend/app/core/security.py` — the `API_AUTH_TOKEN` / `X-API-Key` check applied to all
  `/api/*` routers. A single shared secret, not a user system; replace it if a phase needs
  per-user auth.
- `backend/app/jobs/` — discovery/price-monitor pipelines, callable today, intended to be
  scheduler-triggered later (Phase 2+).

## VERIFIED FINDINGS (so future agents don't re-research these)

- **MercadoLibre's public search endpoint is no longer open.** `GET
  https://api.mercadolibre.com/sites/{site_id}/search` — often cited in older tutorials as
  usable without auth — returned `403 forbidden` when tested live (2026-09-17), with and without
  a browser-like User-Agent. Do not build against it as a no-auth endpoint; assume OAuth/App
  credentials are required for this API now, same as everything else in `mercadolibre.py`.
- **Dropi** (dropi.co) is Colombia's dominant dropshipping platform and matches this project's
  business model closely (verified suppliers, pay-on-delivery, ship-direct-to-customer). It has
  an integration API (`dropi-integration-key` header, per third-party-hosted docs found during
  research) but it is not self-serve/public — it requires an active Dropi account and a key
  generated from their panel. Treat as the most likely first real supplier integration once the
  user has that account; do not implement against unverified third-party doc mirrors — get the
  key and official docs from Dropi directly first.

## FUTURE ROADMAP

- **Phase 1 — Foundation** *(current state)*: domain model, deterministic engines, API,
  dashboard, Claude enrichment hook, adapter interfaces, mock source, seed data, tests.
- **Phase 2 — Product discovery**: real source adapters, scheduled discovery jobs.
- **Phase 3 — Arbitrage engine**: richer cost modeling, smarter product matching.
- **Phase 4 — MercadoLibre integration**: real OAuth + verified endpoints.
- **Phase 5 — Automated listings**: create/update listings from approved opportunities.
- **Phase 6 — Order monitoring**: automatic order detection (webhook/polling) driving
  `order_service.create_order_from_opportunity`.
- **Phase 7 — Semi-automated purchasing**: assist/automate the manual supplier-purchase step.
- **Phase 8 — Analytics and optimization**: historical performance, source reliability, pricing
  strategy tuning.

When implementing a later phase, prefer extending the existing service/integration boundaries
over restructuring them — the interfaces in `integrations/base.py` and the engine split in
`services/` were designed for this growth path.
