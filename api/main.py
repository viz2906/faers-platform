"""
FastAPI application for FAERS Analytics Platform
"""

import time
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from api.dependencies import init_db_pool, init_redis, init_llm
from api.routes import analytics, nlp, ingestion

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize connections on startup, clean up on shutdown."""
    logger.info("Starting FAERS Analytics API...")
    init_db_pool()
    init_redis()
    init_llm()
    logger.info("All connections initialized.")
    yield
    logger.info("Shutting down FAERS Analytics API.")

app = FastAPI(
    title="FAERS Analytics API",
    description="""
FDA Adverse Event Reporting System (FAERS) Analytics Platform.

Pre-built analytics endpoints and a natural language query interface for FAERS data.

Data source: https://fis.fda.gov/extensions/FPD-QDE-FAERS/FPD-QDE-FAERS.html

FAERS data reflects voluntary adverse event reports, not proven drug causation.
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request timing middleware
@app.middleware("http")
async def add_timing_header(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    elapsed = round((time.time() - start) * 1000)
    response.headers["X-Response-Time-Ms"] = str(elapsed)
    return response

# Global error handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.url}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )

# Routes
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["Analytics"])
app.include_router(nlp.router, prefix="/api/v1/nlp", tags=["Natural Language Query"])
app.include_router(ingestion.router, prefix="/api/v1", tags=["Ingestion"])

@app.get("/", tags=["Health"])
async def root():
    return {
        "name": "FAERS Analytics API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "endpoints": {
            "analytics": "/api/v1/analytics",
            "nlp_query": "/api/v1/nlp/query",
        },
    }

@app.get("/livez", tags=["Health"], include_in_schema=False)
async def liveness():
    """Lightweight liveness probe — no I/O, used by Docker HEALTHCHECK."""
    return {"ok": True}


@app.get("/health", tags=["Health"])
async def health():
    from api.dependencies import _db_pool, _redis_client
    db_ok = False
    redis_ok = False

    try:
        conn = _db_pool.getconn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM faers_demo")
            total_cases = cur.fetchone()[0]
        _db_pool.putconn(conn)
        db_ok = True
    except Exception as e:
        total_cases = 0
        logger.warning(f"DB health check failed: {e}")

    try:
        if _redis_client:
            _redis_client.ping()
            redis_ok = True
    except Exception:
        pass

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
        "cache": "connected" if redis_ok else "disconnected",
        "total_cases_loaded": total_cases,
    }
