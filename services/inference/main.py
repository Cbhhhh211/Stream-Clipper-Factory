"""
GPU inference service — runs ASR (Whisper) and ML models on dedicated GPU hardware.

Deployed separately from CPU workers. Scales independently based on GPU utilization.

Run:
    uvicorn services.inference.main:app --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .model_registry import ModelRegistry
from .routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load models at startup, release at shutdown."""
    registry = ModelRegistry()
    registry.load_whisper(
        model_size=os.getenv("WHISPER_MODEL", "large-v3"),
    )
    app.state.registry = registry
    logger.info("Inference service ready — models loaded")
    yield
    registry.unload_all()
    logger.info("Inference service shutting down — models released")


app = FastAPI(
    title="Stream Clipper Inference Service",
    version="2.0.0",
    description="GPU-accelerated ASR and ML inference",
    lifespan=lifespan,
)

app.include_router(router)


@app.get("/health")
async def health():
    registry: ModelRegistry = app.state.registry
    return {
        "status": "healthy",
        "service": "inference",
        "models": registry.status(),
    }
