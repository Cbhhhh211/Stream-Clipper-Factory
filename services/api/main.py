"""
FastAPI application entry point for the Stream Clipper API.

Run:
    uvicorn services.api.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _cors_origins() -> list[str]:
    configured = os.getenv("CORS_ORIGINS", "").strip()
    if configured:
        return [x.strip() for x in configured.split(",") if x.strip()]
    return [
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]


RATE_LIMIT_RPM = int(os.getenv("API_RATE_LIMIT_RPM", "180"))
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)

def _resolve_api_router():
    """
    Resolve API router based on API_MODE.

    API_MODE values:
      - lite: always use lightweight local routes
      - full: always use SaaS full routes (raise if unavailable)
      - auto: try full, fallback to lite
    """
    mode = os.getenv("API_MODE", "lite").strip().lower()

    if mode == "lite":
        from .lite_routes import router as _router
        return _router, "lite"

    if mode == "full":
        from .routes import router as _router
        return _router, "full"

    # auto mode
    try:
        from .routes import router as _router
        return _router, "full"
    except Exception as exc:  # pragma: no cover - fallback for missing infra deps
        from .lite_routes import router as _router
        logger.warning(
            "API_MODE=auto fallback to lite because full API dependencies are unavailable: %s",
            exc,
        )
        return _router, "lite"


router, ACTIVE_API_MODE = _resolve_api_router()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Stream Clipper API starting up (mode=%s)", ACTIVE_API_MODE)
    yield
    logger.info("Stream Clipper API shutting down")


app = FastAPI(
    title="Stream Clipper API",
    version="2.0.0",
    description="Scalable SaaS API for automatic stream highlight clipping",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.middleware("http")
async def simple_rate_limit(request: Request, call_next):
    """
    Lightweight in-memory rate limiter.

    Controlled by API_RATE_LIMIT_RPM:
      - <=0 disables rate limiting
      - >0 limits each client IP to N requests/min
    """
    if RATE_LIMIT_RPM <= 0:
        return await call_next(request)

    if request.url.path.startswith("/health"):
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    cutoff = now - 60.0
    bucket = _rate_buckets[client_ip]

    while bucket and bucket[0] < cutoff:
        bucket.popleft()

    if len(bucket) >= RATE_LIMIT_RPM:
        return JSONResponse(
            status_code=429,
            content={
                "detail": "Rate limit exceeded",
                "limit_per_minute": RATE_LIMIT_RPM,
            },
        )

    bucket.append(now)
    return await call_next(request)


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "api", "mode": ACTIVE_API_MODE}
