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
  integrations/       base adapter interfaces + Claude client + MercadoLibre skeleton + mock source
  repositories/       thin generic DB-access helper
  jobs/               discovery / price-monitor pipelines (callable now, schedulable later)

frontend/
  app.py              Streamlit dashboard entrypoint
  api_client.py        HTTP client calling the FastAPI backend
  pages/               Opportunities, Products, Orders, Marketplaces, Settings
  components/           metrics, tables, opportunity detail card

tests/                pytest suite (pricing, classification, API, health)
scripts/seed.py       loads fictional demo data
alembic/               DB migrations (SQLite now, Postgres-ready)
```

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
- **Database:** SQLite for the MVP (swap `DATABASE_URL` for PostgreSQL later — no code changes needed)
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
| `DATABASE_URL` | SQLAlchemy URL | `sqlite:///./data/arbitrage.db` |
| `API_HOST` / `API_PORT` | uvicorn bind address | `127.0.0.1` / `8000` |
| `BACKEND_API_URL` | URL the Streamlit app calls | `http://127.0.0.1:8000` |
| `ANTHROPIC_API_KEY` | Claude API key (optional) | empty |
| `ANTHROPIC_MODEL` | Claude model id | `claude-sonnet-5` |
| `MIN_ROI` | Opportunity engine threshold | `0.30` |
| `MIN_NET_PROFIT` | Opportunity engine threshold (COP) | `20000` |
| `MAX_RISK_SCORE` | Opportunity engine threshold | `0.50` |
| `DEFAULT_CURRENCY` | Display currency | `COP` |

Never commit `.env` (it's git-ignored). `ANTHROPIC_API_KEY` is read only from the environment —
it is never hard-coded.

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

## Running tests

```bash
poetry run pytest
```

Covers: gross/net profit, ROI, margin (including zero-cost/zero-price edge cases), opportunity
classification (rejected/review/promising/approved), the arbitrage engine's DB persistence,
product CRUD, and the health endpoint. No test requires network access or a real Anthropic key.

## Lint / format

```bash
poetry run ruff check .
poetry run ruff format .
poetry run mypy backend
```

## Current limitations

- **MercadoLibre is not integrated.** `backend/app/integrations/mercadolibre.py` is a skeleton
  whose methods raise `NotImplementedError` with TODOs — it does not call any real endpoint.
  Wiring it up requires a registered MercadoLibre application, OAuth credentials, and verified
  endpoint documentation.
- **No real supplier/source is integrated.** `backend/app/integrations/mock_source.py` is a
  clearly-fake, in-memory catalog for development and tests.
- **No scheduler.** `backend/app/jobs/discovery.py` and `price_monitor.py` are callable
  pipelines, not cron/queue-scheduled jobs yet.
- **Order detection is manual.** There is no live marketplace webhook/poll creating `Order` rows
  automatically yet; `services/order_service.py` expects to be called once a sale is known.
- **No authentication.** The API and dashboard are unauthenticated — fine for local/single-user
  use, not for a public deployment as-is.
- Manual opportunity status overrides ("Mark reviewed" / "Approve" / "Reject" buttons) are
  visible as placeholders in the UI but not yet backed by an API endpoint.

## Roadmap

1. **Foundation** *(this repo)* — domain model, deterministic pricing/opportunity engines, API,
   dashboard, Claude enrichment, integration interfaces, seed data, tests.
2. **Product discovery** — real source adapters, scheduled discovery jobs.
3. **Arbitrage engine refinement** — smarter product matching, richer cost modeling (taxes,
   payment processor fees per marketplace).
4. **MercadoLibre integration** — OAuth, catalog/listing read, order polling.
5. **Automated listings** — create/update/price-sync listings from approved opportunities.
6. **Order monitoring** — webhook or polling-based order detection and alerting.
7. **Semi-automated purchasing** — one-click or API-assisted supplier purchase once a sale lands.
8. **Analytics and optimization** — historical performance, source reliability scoring, pricing
   strategy tuning.
