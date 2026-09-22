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
4. **Never invent API endpoints.** `integrations/mercadolibre.py`'s `authenticate()` is REAL
   (OAuth2, verified 2026-09-21 — see VERIFIED FINDINGS below); every other method still raises
   `NotImplementedError` with a TODO, because we don't have those endpoints' real request/response
   shapes confirmed yet. Do not fill in guessed endpoint URLs or fabricate response shapes —
   confirm against official docs first, the same way auth was done one endpoint at a time.
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
- `backend/app/integrations/dropi.py` — skeleton `SourceAdapter` for Dropi, same pattern as
  `mercadolibre.py` (every method raises `NotImplementedError` with a TODO). Blocked — see
  VERIFIED FINDINGS below before touching this.
- `backend/app/integrations/cjdropshipping.py` — a REAL, working `SourceAdapter` against
  CJdropshipping's documented API (login, product search, product detail all confirmed live
  against the user's own account, including a self-throttle for CJ's real 1 req/sec limit and a
  fix for `variants[].inventories` frequently being `null` even on well-stocked products — see
  the file's docstring). This is the project's actual functioning supplier integration right now.
  `scripts/discover_cj.py` runs the real discovery pipeline against it (contrast
  `scripts/discover_demo.py`, which uses the fake DummyJSON source). Its USD prices are converted
  to COP by `backend/app/services/currency.py` (a configurable `USD_TO_COP_RATE`, not a live FX
  call) before evaluation, so opportunities now classify normally — verified live 2026-09-18 with
  a fresh local DB: 4 approved, 3 promising, 13 rejected out of 20, instead of 20/20 rejected.
- `backend/app/core/security.py` — the `API_AUTH_TOKEN` / `X-API-Key` check applied to all
  `/api/*` routers. A single shared secret, not a user system; replace it if a phase needs
  per-user auth.
- `backend/app/jobs/` — discovery/price-monitor pipelines, callable today, intended to be
  scheduler-triggered later (Phase 2+).

## VERIFIED FINDINGS (so future agents don't re-research these)

- **MercadoLibre's app registration console ("DevCenter") is a separate site from its API docs.**
  `developers.mercadolibre.com.co` is documentation only ("API Docs") — creating/managing an app
  happens at `developers.mercadolibre.com.co/devcenter`, reachable from the docs site's "Primeros
  pasos" page via the "Ir a vincular mi cuenta" link. Confirmed live 2026-09-21: visiting
  `/devcenter` the first time triggers a MercadoPago identity-verification gate
  (`mercadopago.com.co/shield?id=USER_BLOCKER`) before granting access — expected, not a bug; the
  account owner has to complete it themselves.
- **MercadoLibre OAuth2 (Authorization Code, server-side) is real and implemented** — verified
  against MercadoLibre's own docs (developers.mercadolibre.com.ar/es_ar/autenticacion-y-
  autorizacion, updated 2026-07-15) on 2026-09-21. `/api/marketplaces/mercadolibre/authorize` +
  `/callback` (backend/app/api/mercadolibre_oauth.py) run the flow and persist tokens on
  `MarketplaceCredential`; `MercadoLibreAdapter.authenticate()` refreshes and verifies live
  against `/users/me`. These two OAuth routes are deliberately NOT behind `require_api_key` —
  they're hit by the seller's browser via redirect, which can't carry our internal API key.
  `create_listing`/`update_listing`/`update_price` are also real now (verified 2026-09-21 by
  actually publishing two live items — MCO4468282932, a throwaway "Item de Prueba" test listing
  in category MCO412060 "Llaveros", and MCO4468548662, a real discovered opportunity, a portable
  projector). `search_products`/`get_product`/`get_listing`/`get_orders` are still
  `NotImplementedError`. Two real, non-obvious requirements found while publishing:
  COP (and other zero-decimal currencies) reject a price with any decimal point at all
  (`item.price.invalid`); and pictures are effectively mandatory in practice even for listing
  types whose `GET /sites/{id}/listing_prices` response says `requires_picture: false` (e.g.
  "bronze" silently normalizes to "gold_special" server-side, which does require one).
- **A seller account needs a pickup/shipping address configured before it can list anything** —
  `POST /items` returns `403 seller.unable_to_list` with `cause: ["address_pending"]` otherwise.
  Not something this codebase can fix; the account owner has to add it via mercadolibre.com.co
  ("Vender" flow surfaces the prompt directly).
- **CJ's real China->Colombia shipping is far more expensive/slower than the old $29,000 COP
  guess.** Verified live 2026-09-21 via CJ's real freight calculator (`POST /api2.0/v1/logistic/
  freightCalculate`) for an actual discovered product (770g projector): options ranged from
  $20.56 USD / 20-60 days (cheapest) to $105.82 USD / 3-7 days (DHL Official) — a 5x cost spread
  tied directly to delivery speed. `Settings.shipping_cost_cop` default updated to ~$70,700 COP
  (~$22.58 USD, "CJPacket Latin America Sensitive", 6-12 days) as a more realistic single
  default — still not a per-product number; use the freight calculator for anything
  price-sensitive. This also means MercadoLibre's own reputation system (fast dispatch/delivery
  expectations under standard ME2) is in real tension with CJ's realistic delivery windows —
  the cheap options are too slow for ME2's implicit SLA, the fast option (DHL) often costs more
  than the entire item.
- **MercadoLibre has a "Cross Border Trade" (CBT) program, already active in Colombia**, that
  labels listings "compra internacional" so buyers expect longer delivery — this is likely the
  *correct* mechanism for CJ-sourced dropshipping (avoids the ME2 fast-dispatch mismatch above),
  but it's typically for accounts registered as actual foreign/cross-border merchants (Global
  Selling), not something toggled on a normal Colombian seller account's regular listing.
  Whether this account is eligible is unverified — investigate before relying on it.
- **MercadoLibre's public search endpoint is no longer open.** `GET
  https://api.mercadolibre.com/sites/{site_id}/search` — often cited in older tutorials as
  usable without auth — returned `403 forbidden` when tested live (2026-09-17), with and without
  a browser-like User-Agent. Do not build against it as a no-auth endpoint; assume OAuth/App
  credentials are required for this API now, same as everything else in `mercadolibre.py`.
- **Dropi has a real API at `api.dropi.co`, but it's likely gated to white-label partners.**
  `https://api.dropi.co/docs` serves a genuine, officially-hosted OpenAPI 3.0 spec (contact:
  soporteti@dropi.co) — confirmed live 2026-09-17. It documents only 8 endpoints (auth, register,
  categories, users, warehouses, cancellation reasons) — none for product catalog/pricing/orders.
  Live probing confirmed `POST /api/products` and `POST /integrations/products` exist (401, not
  404) but their schema isn't in the public spec. The user registered a normal (non-white-label)
  dropshipper account and tried `POST /integrations/login` with `white_brand_id` empty — it
  returned `{"message": "Attempt to read property \"id\" on null", "status": 400}`, a server-side
  null-pointer error from looking up a white-label brand by that (empty) ID. This strongly
  suggests `/integrations/*` requires a `white_brand_id` that only white-label reseller partners
  have, not regular individual dropshippers. Status: waiting on a reply from Dropi support
  (soporteti@dropi.co) asking whether individual dropshippers get API access at all. Do not
  attempt this login flow again with real credentials from chat — if credentials are needed for
  further diagnosis, have the user run a local script themselves (see git history:
  `scripts/dropi_explore.py`) and paste back only the printed output, never the password.
  IMPORTANT: the user's real Dropi password was pasted into chat once during this — they were
  told to change it immediately; if you see a plaintext password in future output, flag it the
  same way and never write it to any file.
- **CJdropshipping is the real, working alternative — already integrated.** Self-serve API,
  officially documented at developers.cjdropshipping.com, account + API key created directly by
  the user, no partner approval needed. See `cjdropshipping.py`. Trade-off: it's a China-based
  global supplier, not a Colombian one, so shipping times to Colombia are longer than Dropi's
  promised 24-72h — keep Dropi as the long-term goal if support unblocks it, but CJ is what
  actually works today. Auth note: `POST /integrations/authentication/getAccessToken` initially
  looked like it took `{email, password}` (per a `.cn`-domain doc mirror found via search), but
  the user pasted the *actual* docs from inside their own CJ account showing the real, current
  auth is `{"apiKey": "CJUserNum@api@..."}` only — confirmed live (a bad key returns
  `{"code": 1600005, "message": "APIkey is wrong..."}`). The email/password version was wrong;
  trust the user's own account docs over search-engine-found mirrors when they conflict.
- **Falabella (falabella.com.co) has no official product API for individual sellers, but is
  genuinely scrapeable and now integrated** — `backend/app/integrations/falabella_source.py`.
  Verified live 2026-09-22: `robots.txt` allows all crawlers except account/checkout paths; the
  site is a Next.js app that embeds full structured product data (name, brand, prices, stock) as
  JSON in a `<script id="__NEXT_DATA__">` tag on both search (`/falabella-co/search?Ntt=`) and
  product (`/falabella-co/product/{id}`, slug optional) pages — a plain unauthenticated GET + JSON
  parse, no headless browser needed. This is a **retail arbitrage** source, structurally different
  from CJ's wholesale dropshipping: no supplier-ships-to-customer flow (buying/shipping is a
  manual step after a sale, briefly holding the item), and domestic fulfillment (no international
  freight) — `scripts/discover_falabella.py` overrides `run_discovery`'s CJ-tuned
  `shipping_cost_cop`/`min_buy_price_cop` with much lower domestic estimates.
- **The estimated-sell-price multiplier (1.8x) is wrong for a retail source like Falabella** —
  found by actually running discovery against it (2026-09-22): applying a wholesale-arbitrage
  markup on top of an already-retail price produced wildly overstated "opportunities" (e.g. a
  $499,900 COP blender "resold" at $899,820 — 80% more than Falabella's own listed price, which
  no real buyer would pay when the same product is available directly from Falabella for less).
  Fixed by adding `SourceProductInfo.reference_price` (a source's own real reference/list price —
  Falabella's crossed-out "normal price" next to a discounted one) — `run_discovery` now uses it
  as `sell_price` directly when a source provides it, falling back to the multiplier only when it
  doesn't (e.g. CJ, which has no such concept). Re-running discovery after the fix produced a
  believable mix (18 approved / 25 promising / 57 rejected out of 100), not the earlier
  near-100%-"promising" false positive.

## DEPLOYED STATE (as of 2026-09-17)

The app is live: Neon Postgres (a project separate from this user's other "Jobs" app — do not
reuse that one's database), FastAPI backend on Render (`render.yaml` blueprint), Streamlit
frontend on Streamlit Community Cloud. The Streamlit app is deployed as **public** (not
Streamlit's "private" flag) because the free tier only allows one private app per workspace and
that slot is already used by the user's Jobs project — access is instead restricted by the
`APP_PASSWORD` gate (`frontend/auth_gate.py`), same pattern as Jobs. Render's free tier suspends
the service after idle time (cold start on first request); this is expected, not a bug.

## FUTURE ROADMAP

- **Phase 1 — Foundation** *(current state)*: domain model, deterministic engines, API,
  dashboard, Claude enrichment hook, adapter interfaces, mock source, seed data, tests.
- **Phase 2 — Product discovery**: real source adapters, scheduled discovery jobs.
- **Phase 3 — Arbitrage engine**: richer cost modeling, smarter product matching.
- **Phase 4 — MercadoLibre integration**: real OAuth (done, 2026-09-21) + verified endpoints
  (search/create/update listings, orders — still pending, see `mercadolibre.py`).
- **Phase 5 — Automated listings**: create/update listings from approved opportunities.
- **Phase 6 — Order monitoring**: automatic order detection (webhook/polling) driving
  `order_service.create_order_from_opportunity`.
- **Phase 7 — Semi-automated purchasing**: assist/automate the manual supplier-purchase step.
- **Phase 8 — Analytics and optimization**: historical performance, source reliability, pricing
  strategy tuning.

When implementing a later phase, prefer extending the existing service/integration boundaries
over restructuring them — the interfaces in `integrations/base.py` and the engine split in
`services/` were designed for this growth path.
