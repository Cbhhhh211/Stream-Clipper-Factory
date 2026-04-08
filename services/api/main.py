"""
FastAPI application entry point for the Stream Clipper API.

Run:
    uvicorn services.api.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .public_routes import router as public_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = ROOT / "frontend" / "dist"
FRONTEND_ASSETS = FRONTEND_DIST / "assets"


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
app.include_router(public_router)


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


@app.get("/assets/{asset_path:path}", include_in_schema=False)
async def frontend_assets(asset_path: str):
    target = (FRONTEND_ASSETS / asset_path).resolve()
    if not FRONTEND_ASSETS.exists() or FRONTEND_ASSETS not in target.parents or not target.is_file():
        return JSONResponse(status_code=404, content={"detail": "Asset not found"})
    return FileResponse(target)


@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str):
    if full_path.startswith(("api/", "docs", "redoc", "openapi.json", "health")):
        return JSONResponse(status_code=404, content={"detail": "Not found"})

    if not FRONTEND_DIST.exists():
        return JSONResponse(
            status_code=404,
            content={"detail": "Frontend build not found. Run `npm run build` in frontend/ first."},
        )

    requested = (FRONTEND_DIST / full_path).resolve() if full_path else FRONTEND_DIST / "index.html"
    if full_path and requested.is_file() and FRONTEND_DIST in requested.parents:
        return FileResponse(requested)

    index_file = FRONTEND_DIST / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)

    return JSONResponse(status_code=404, content={"detail": "Frontend entry not found"})
