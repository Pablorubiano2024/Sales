"""FastAPI application entrypoint.

Run with:
    python -m uvicorn backend.app.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from backend.app.api import health, marketplaces, opportunities, orders, products, settings
from backend.app.core.config import get_settings
from backend.app.core.database import init_db
from backend.app.core.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up: ensuring database is initialized")
    init_db()
    yield
    logger.info("Shutting down")


app_settings = get_settings()

app = FastAPI(
    title=app_settings.app_name,
    description=(
        "Automated product arbitrage platform: discover, analyze, calculate, "
        "publish, sell, purchase and track profit — without holding inventory."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


app.include_router(health.router)
app.include_router(products.router)
app.include_router(opportunities.router)
app.include_router(orders.router)
app.include_router(marketplaces.router)
app.include_router(settings.router)
