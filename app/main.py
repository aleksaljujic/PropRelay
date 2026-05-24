"""
PropFlow — FastAPI application entry point.

Startup sequence:
  1. Verify database connectivity
  2. Verify Redis connectivity
  3. Mount routers + middleware

Shutdown sequence:
  1. Dispose SQLAlchemy engine connection pool
  2. Close Redis connection
"""
import uuid
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.router import api_router
from app.config import settings
from app.core.redis import close_redis, get_redis
from app.database import engine
from app.workers.timeout_worker import start_timeout_worker, stop_timeout_worker

# ---------------------------------------------------------------------------
# Structured logging setup
# ---------------------------------------------------------------------------
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer() if settings.debug else structlog.processors.JSONRenderer(),
    ]
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan — startup & shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN001
    # ── Startup ────────────────────────────────────────────────────────────
    logger.info("PropFlow starting", env=settings.app_env, debug=settings.debug)

    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection OK")
    except Exception as exc:
        logger.warning("Database connection check failed", error=str(exc))

    try:
        redis = await get_redis()
        await redis.ping()
        logger.info("Redis connection OK")
    except Exception as exc:
        logger.warning("Redis connection check failed", error=str(exc))

    start_timeout_worker()
    logger.info("PropFlow ready", version="0.1.0")
    yield

    # ── Shutdown ───────────────────────────────────────────────────────────
    logger.info("PropFlow shutting down")
    await stop_timeout_worker()
    await engine.dispose()
    await close_redis()
    logger.info("PropFlow stopped")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="PropFlow",
    description=(
        "AI-powered property management for EU landlords. "
        "WhatsApp-first multi-agent system for maintenance triage and dispatch."
    ),
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)

# CORS — allow localhost origins for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request-ID middleware (adds a correlation ID to every request)
# ---------------------------------------------------------------------------

@app.middleware("http")
async def add_request_id(request: Request, call_next: Any) -> Any:
    request_id = str(uuid.uuid4())
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Meta"])
async def health_check() -> dict[str, str]:
    """
    Liveness + readiness probe.
    Returns 200 with component statuses so load-balancers can route traffic.
    """
    db_status = "ok"
    redis_status = "ok"

    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    try:
        redis = await get_redis()
        await redis.ping()
    except Exception:
        redis_status = "error"

    return {
        "status": "ok" if db_status == "ok" and redis_status == "ok" else "degraded",
        "db": db_status,
        "redis": redis_status,
        "version": "0.1.0",
    }


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(api_router)
