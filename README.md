# Product Arbitrage Platform

An automated product arbitrage / dropshipping platform, initially focused on Colombia and
MercadoLibre. It discovers products that can be bought cheaply from suppliers, identifies
equivalent products that sell for more on marketplaces, calculates real (not naive)
profitability, and ranks opportunities — without holding inventory.

```
DISCOVER → ANALYZE → CALCULATE → PUBLISH → SELL → PURCHASE → SHIP → TRACK PROFIT
```

## Business model

This is **not** traditional inventory-based ecommerce. The intended workflow is:

```
Supplier has product
        ↓
System finds an arbitrage opportunity
        ↓
Product is listed on a marketplace
        ↓
Customer purchases it
        ↓
System detects the order
        ↓
User receives an alert
        ↓
User manually purchases from the supplier
        ↓
Supplier ships directly to the customer
        ↓
System tracks the order and the resulting profit
```

Buying from the supplier only happens **after** a sale is confirmed. Later phases can automate
more of this chain (see Roadmap), but the platform is not designed around warehousing or
inventory management at any stage.

## Architecture

```
backend/app/
  main.py            FastAPI app entrypoint
  api/               HTTP routes (products, opportunities, orders, marketplaces, settings, health)
  core/               config (Settings), database (SQLAlchemy engine/session), logging
  models/             SQLAlchemy ORM models (Product, Source, Marketplace, Opportunity, Order, PriceHistory)
  schemas/            Pydantic request/response schemas
  services/           business logic: pricing_engine, opportunity_engine, arbitrage_engine,
                       product_matcher, order_service, ai_service
  integrations/       base adapter interfaces + Claude client + MercadoLibre skeleton +
                       Dropi skeleton + CJdropshipping (real supplier) + mock source +
                       DummyJSON (real HTTP demo source)
  repositories/       thin generic DB-access helper
  jobs/               discovery / price-monitor pipelines (callable now, schedulable later)

frontend/
  app.py              Navigation shell only: page config, auth gate, styles, and
                       st.navigation(position="top") — the top nav bar (see below)
  api_client.py        HTTP client calling the FastAPI backend
  auth_gate.py          optional APP_PASSWORD gate for public deployments
  i18n.py               English (API) -> Spanish (UI) status label mapping
  views/               Inicio, Oportunidades, Productos, Órdenes, Marketplaces, Configuración
                       (the actual page content — UI text is in Spanish, see note below)
  components/           metrics, tables, opportunity detail card

tests/                pytest suite (pricing, classification, API, health)
scripts/seed.py       loads fictional demo data
alembic/               DB migrations (SQLite now, Postgres-ready)
```

**The Streamlit UI is in Spanish** (labels, buttons, messages); the backend, code, comments and
this documentation stay in English. `frontend/i18n.py` maps the API's English enum values
(`approved`, `rejected`, ...) to Spanish display labels — those enum values are the API contract
and are not translated.

**Financial math is deterministic and AI-free.** `services/pricing_engine.py` and
`services/opportunity_engine.py` compute gross/net profit, ROI, margin and status
classification using `Decimal` arithmetic and configurable thresholds — Claude is never in that
loop. `services/ai_service.py` + `integrations/claude.py` add optional qualitative
enrichment (demand/competition/risk scores, reasoning) on top, and the app works fine without an
Anthropic API key configured.

## Technology stack

- **Backend:** Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic, httpx, uvicorn
- **Frontend:** Streamlit
- **AI:** Anthropic Claude API (`anthropic` SDK), structured/Pydantic-validated output
- **Database:** SQLite by default (local/dev); set `DATABASE_URL` to a Postgres connection string
  (e.g. from [Neon](https://neon.tech)) to switch — no code changes needed, same pattern as this
  author's other project (Jobs): unset = SQLite, set = Postgres
- **Config:** pydantic-settings + `.env`
- **Testing:** pytest
- **Lint/format:** Ruff; `mypy` where useful
- No Docker.

## Setup

Dependencies are managed with [Poetry](https://python-poetry.org/). This project targets
Python 3.12+; a local virtualenv is used (`poetry env use <python3.12 interpreter>` if needed).

```bash
poetry install
cp .env.example .env
# edit .env — at minimum you can leave ANTHROPIC_API_KEY blank; everything but
# AI enrichment works without it.
```

### Environment variables (`.env`)

| Variable | Purpose | Default |
|---|---|---|
| `APP_ENV` | `development` / `production` | `development` |
| `DATABASE_URL` | SQLite path, or a Postgres URL (Neon) — blank/sqlite = local file | `sqlite:///./data/arbitrage.db` |
| `API_HOST` / `API_PORT` | uvicorn bind address | `127.0.0.1` / `8000` |
| `API_AUTH_TOKEN` | Shared secret required as `X-API-Key` on `/api/*` (blank = disabled) | empty |
| `BACKEND_API_URL` | URL the Streamlit app calls | `http://127.0.0.1:8000` |
| `APP_PASSWORD` | Shared password gate for the Streamlit UI (blank = disabled) | empty |
| `ANTHROPIC_API_KEY` | Claude API key (optional) | empty |
| `ANTHROPIC_MODEL` | Claude model id | `claude-sonnet-5` |
| `MIN_ROI` | Opportunity engine threshold | `0.30` |
| `MIN_NET_PROFIT` | Opportunity engine threshold (COP) | `20000` |
| `MAX_RISK_SCORE` | Opportunity engine threshold | `0.50` |
| `DEFAULT_CURRENCY` | Display currency | `COP` |
| `USD_TO_COP_RATE` | Manual USD→COP rate, used to convert source prices (e.g. CJdropshipping) before evaluating against COP thresholds — see `backend/app/services/currency.py` | `3130` |

Never commit `.env` (it's git-ignored). `ANTHROPIC_API_KEY` is read only from the environment —
it is never hard-coded.

### API authentication

`/health` is always open. Every `/api/*` endpoint is protected by `backend/app/core/security.py`:
if `API_AUTH_TOKEN` is unset, auth is disabled (convenient for local-only use); if it's set,
requests must include a matching `X-API-Key` header or get a `401`. The Streamlit frontend reads
the same `.env` and attaches the header automatically (`frontend/api_client.py`). Set this before
deploying the API anywhere reachable beyond localhost — it's a single shared secret, not a full
user/auth system, and is meant to be replaced if a later phase needs per-user accounts.

## Running the backend

```bash
poetry run python -m uvicorn backend.app.main:app --reload --port 8000
```

Interactive API docs: http://127.0.0.1:8000/docs (OpenAPI: `/openapi.json`).

The database and `data/` directory are created automatically on startup. Table creation on
startup is a pragmatic MVP shortcut — Alembic migrations under `alembic/` are the source of
truth for schema evolution going forward (`poetry run alembic revision --autogenerate -m "..."`,
`poetry run alembic upgrade head`).

## Running the frontend

```bash
poetry run streamlit run frontend/app.py
```

Requires the backend to be running (it talks to it over HTTP via `BACKEND_API_URL`).

## Seed data

```bash
poetry run python scripts/seed.py
```

Loads a mock supplier, a MercadoLibre-Colombia marketplace entry, and five fictional products
with a deliberate spread of outcomes (profitable/unprofitable, different ROIs, different risk
levels) so the dashboard has something to show immediately. All data is clearly fictional —
nothing is scraped.

```bash
poetry run python scripts/discover_demo.py
```

Exercises the real discovery pipeline (`jobs/discovery.run_discovery`) against
`DummyJsonSourceAdapter` — a genuine HTTP integration (real requests, real error handling)
against the public [DummyJSON](https://dummyjson.com) demo product API. It is **not** a real
supplier (prices are fictional and in USD), but it proves out the adapter pattern.

```bash
poetry run python scripts/discover_cj.py
```

The same pipeline against **CJdropshipping — an actual, working supplier** (requires `CJ_API_KEY`
in `.env`; see `backend/app/integrations/cjdropshipping.py`). This creates real `Product` /
`SourceProduct` / `Opportunity` rows from CJ's live catalog. Prices are real, in USD; the
discovery job converts them to COP (via `services/currency.py` and `USD_TO_COP_RATE`) before
evaluating against the COP-denominated thresholds, so opportunities now classify normally
(rejected/promising/approved) instead of always coming back rejected.

```bash
poetry run python scripts/discover_falabella.py
```

The same pipeline against **falabella.com.co — a real Colombian retailer**, no API key needed
(see `backend/app/integrations/falabella_source.py`). This is retail arbitrage, not wholesale
dropshipping — different fulfillment model (you buy and ship yourself after a sale, domestically)
and different estimated-sell-price logic (Falabella's own real "normal price" next to a discount,
not a wholesale-markup multiplier). Requires no credentials; just needs the real site to be up.

## Running tests

```bash
poetry run pytest
```

Covers: gross/net profit, ROI, margin (including zero-cost/zero-price edge cases), opportunity
classification (rejected/review/promising/approved), the arbitrage engine's DB persistence,
product CRUD, and the health endpoint. No test requires network access or a real Anthropic key.

## Deployment

Three pieces, each hosted separately (no Docker, all free-tier friendly):

1. **Database — [Neon](https://neon.tech) (Postgres)**
   Create a project, copy its connection string (`postgresql://user:password@host/db?sslmode=require`).
   That's the only thing you need from Neon — SQLAlchemy handles the rest via `DATABASE_URL`.

2. **Backend — [Render](https://render.com)**, via the included `render.yaml` blueprint:
   - Render dashboard → **New → Blueprint** → connect this GitHub repo.
   - When prompted for the `sync: false` variables, set:
     - `DATABASE_URL` → the Neon connection string from step 1
     - `API_AUTH_TOKEN` → a secret you make up (required — see API authentication above)
     - `ANTHROPIC_API_KEY` → optional, only if you want AI enrichment live
   - Render builds with Poetry (`poetry install --no-root --only main`) and runs
     `uvicorn backend.app.main:app --host 0.0.0.0 --port $PORT` — no Dockerfile involved.
   - Once deployed, note the public URL (e.g. `https://product-arbitrage-api.onrender.com`) and
     confirm `<url>/health` returns `{"status": "ok"}`.
   - Run migrations / seed against the live database once, from your machine:
     `DATABASE_URL='<neon url>' poetry run alembic upgrade head` (or `init_db()` runs this
     automatically on the deployed app's own startup, same as locally).

3. **Frontend — [Streamlit Community Cloud](https://share.streamlit.io)**
   - Sign in with GitHub, **New app**, pick this repo/branch, main file path: `frontend/app.py`.
   - Streamlit Cloud installs the root `requirements.txt` (frontend-only deps — see that file).
   - In the app's **Settings → Secrets**, add:
     ```toml
     BACKEND_API_URL = "https://product-arbitrage-api.onrender.com"
     API_AUTH_TOKEN = "the same value you set in Render"
     APP_PASSWORD = "a password to gate the public dashboard (optional but recommended)"
     ```
   - Deploy. `frontend/auth_gate.py` will prompt for `APP_PASSWORD` before showing any page if
     it's set; leave it unset for an open dashboard.

Render's free web services spin down after inactivity and take a few seconds to wake up on the
next request — expect a slow first load after idle periods; this is a free-tier tradeoff, not a
bug. Neon's free tier similarly suspends compute when idle (`pool_pre_ping=True` on the backend's
engine handles the resulting stale-connection case gracefully).

## Lint / format

```bash
poetry run ruff check .
poetry run ruff format .
poetry run mypy backend
```

## Current limitations

- **MercadoLibre: OAuth is real, everything past login is still a skeleton.**
  `ML_CLIENT_ID`/`ML_CLIENT_SECRET`/`ML_REDIRECT_URI` (from a real app registered at
  developers.mercadolibre.com.co/devcenter) enable a genuine Authorization Code OAuth flow —
  `/api/marketplaces/mercadolibre/authorize` and `/callback` (or the "Conectar cuenta de
  MercadoLibre" button in the Marketplaces view), verified live against `/users/me`. But
  `search_products`/`create_listing`/`update_price`/`get_orders` etc. all still raise
  `NotImplementedError` — connecting the account doesn't yet let you publish or read anything.
- **`cjdropshipping.py` is the only real, working supplier integration** — set `CJ_API_KEY` (from
  your own CJdropshipping account: Apps → install "API" → "Get API Key" page) to use it. It's a
  global (China-based) dropshipping supplier, not a Colombian one, so shipping times to Colombia
  are longer than a local supplier's — it's here because its API is genuinely self-serve and
  documented, unlike Dropi as of this writing.
- **Dropi is not integrated.** `dropi.py` is a skeleton like `mercadolibre.py`. Dropi (dropi.co)
  matches this project's business model closely (local Colombian suppliers, pay-on-delivery), but
  its `/integrations/login` endpoint errored on a regular dropshipper account during testing — it
  may be scoped to white-label partners only. See `PROJECT_CONTEXT.md` before touching this file.
- **`falabella_source.py` is a real, working retail-arbitrage source** — falabella.com.co has no
  official product API, but is a Next.js app that embeds structured product JSON directly in the
  page (`__NEXT_DATA__`), verified scrapeable (permissive `robots.txt`). Structurally different
  from CJ: retail (not wholesale) prices, domestic (not international) fulfillment, and no
  supplier-ships-for-you flow — see `scripts/discover_falabella.py` for the domestic
  shipping/price-floor overrides this needs. Uses the real "normal price" Falabella itself reports
  next to a discount (`SourceProductInfo.reference_price`) as the estimated resale price, instead
  of CJ's wholesale-markup multiplier — see Current Limitations below for why that distinction
  matters.
- `mock_source.py` is a clearly-fake, in-memory catalog for tests; `dummyjson_source.py` makes
  real HTTP calls but against a public demo API, not a real supplier.
- **Currency conversion uses a manual, not live, FX rate.** `pricing_engine` itself stays
  currency-agnostic by design; `backend/app/services/currency.py` converts USD source prices
  (CJdropshipping) to COP before the discovery job evaluates them, using the configurable
  `USD_TO_COP_RATE` setting rather than a live FX API call (rate drifts slowly enough that this is
  accurate enough for arbitrage decisions — see the module docstring for the reasoning). Update
  `USD_TO_COP_RATE` from the official TRM (banrep.gov.co) if it's drifted.
- **No real marketplace (MercadoLibre) sell-price data — still true for CJ-sourced
  opportunities.** For sources with no `reference_price` (CJ), `run_discovery` estimates the
  selling price as a configurable multiplier of the (converted) buy price — it does not look up
  what similar items actually sell for on MercadoLibre (its public search API returned `403` as
  of this writing). Validate a promising CJ-sourced opportunity's real MercadoLibre price manually
  before trusting it for a real listing decision. Falabella-sourced opportunities instead use
  Falabella's own real "normal price" (`reference_price`) — real market data, but still not a
  MercadoLibre price specifically.
- **No scheduler.** `backend/app/jobs/discovery.py` and `price_monitor.py` are callable
  pipelines, not cron/queue-scheduled jobs yet.
- **Order detection is manual.** There is no live marketplace webhook/poll creating `Order` rows
  automatically yet; `services/order_service.py` expects to be called once a sale is known.
- **Auth is a single shared API key, not a user system.** `API_AUTH_TOKEN` (see above) stops the
  API from being wide open once deployed, but there's no per-user login, roles, or sessions.
- Manual opportunity status overrides ("Mark reviewed" / "Approve" / "Reject" buttons) are
  visible as placeholders in the UI but not yet backed by an API endpoint.

## Roadmap

1. **Foundation** *(this repo)* — domain model, deterministic pricing/opportunity engines, API,
   dashboard, Claude enrichment, integration interfaces, seed data, tests.
2. **Product discovery** — real source adapters, scheduled discovery jobs.
3. **Arbitrage engine refinement** — smarter product matching, richer cost modeling (taxes,
   payment processor fees per marketplace).
4. **MercadoLibre integration** — OAuth (done) → catalog/listing read, order polling.
5. **Automated listings** — create/update/price-sync listings from approved opportunities.
6. **Order monitoring** — webhook or polling-based order detection and alerting.
7. **Semi-automated purchasing** — one-click or API-assisted supplier purchase once a sale lands.
8. **Analytics and optimization** — historical performance, source reliability scoring, pricing
   strategy tuning.
