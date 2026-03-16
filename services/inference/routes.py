"""
Inference service HTTP endpoints.

POST /v1/transcribe  — ASR transcription via Whisper
POST /v1/virality    — Virality score prediction for clip windows
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services.storage.s3 import S3Storage

logger = logging.getLogger(__name__)
router = APIRouter()


def _env_int(name: str, default: int, min_value: int = 1) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_value, value)


# ===================================================================
# Request / Response schemas
# ===================================================================

class TranscribeRequest(BaseModel):
    audio_s3_key: str
    language: str = "zh"
    model_size: str = "large-v3"


class SegmentOut(BaseModel):
    start: float
    end: float
    text: str


class TranscribeResponse(BaseModel):
    segments: List[SegmentOut]
    language: str
    language_probability: float


class ViralityRequest(BaseModel):
    segments_s3_key: str
    danmaku_s3_key: str
    highlights: List[dict]


class ViralityScoreOut(BaseModel):
    composite: float
    predicted_ctr: float
    predicted_share: float


class ViralityResponse(BaseModel):
    scores: List[ViralityScoreOut]


# ===================================================================
# Transcribe endpoint
# ===================================================================

@router.post("/v1/transcribe", response_model=TranscribeResponse)
async def transcribe(req: TranscribeRequest, request: Request):
    """
    Transcribe audio using faster-whisper.

    The audio file is downloaded from S3, processed on GPU, and results returned.
    """
    registry = request.app.state.registry

    if not registry.is_loaded("whisper"):
        raise HTTPException(503, "Whisper model not loaded")

    storage = S3Storage()

    # Download audio from S3 to local temp
    try:
        local_audio = storage.download_temp(req.audio_s3_key, suffix=".wav")
    except Exception as e:
        raise HTTPException(400, f"Failed to download audio: {e}")

    # Run transcription
    try:
        model = registry.get("whisper")
        beam_size = _env_int("ASR_BEAM_SIZE", 1, min_value=1)
        vad_min_silence_ms = _env_int("ASR_VAD_MIN_SILENCE_MS", 1000, min_value=100)
        gen, info = model.transcribe(
            local_audio,
            language=req.language,
            beam_size=beam_size,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": vad_min_silence_ms},
        )

        segments = []
        for seg in gen:
            text = seg.text.strip()
            if text:
                segments.append(SegmentOut(start=seg.start, end=seg.end, text=text))

        logger.info("Transcribed %d segments (lang=%s, prob=%.2f)",
                     len(segments), info.language, info.language_probability)

        return TranscribeResponse(
            segments=segments,
            language=info.language,
            language_probability=info.language_probability,
        )
    except Exception as e:
        logger.exception("Transcription error")
        raise HTTPException(500, f"Transcription failed: {e}")
    finally:
        # Cleanup temp file
        try:
            os.unlink(local_audio)
        except OSError:
            pass


# ===================================================================
# Virality prediction endpoint
# ===================================================================

@router.post("/v1/virality", response_model=ViralityResponse)
async def predict_virality(req: ViralityRequest, request: Request):
    """
    Predict virality scores for highlight clip windows.

    Uses danmaku density, sentiment heuristics, and clip characteristics
    to estimate viral potential. When ML models are loaded, uses learned
    predictions instead.
    """
    storage = S3Storage()

    try:
        segments_data = storage.download_json(req.segments_s3_key)
        danmaku_data = storage.download_json(req.danmaku_s3_key)
    except Exception as e:
        raise HTTPException(400, f"Failed to load data from S3: {e}")

    scores = []
    for hl in req.highlights:
        start = hl.get("start", hl.get("clip_start", 0))
        end = hl.get("end", hl.get("clip_end", 0))
        duration = end - start

        if duration <= 0:
            scores.append(ViralityScoreOut(
                composite=0.0, predicted_ctr=0.0, predicted_share=0.0
            ))
            continue

        # Danmaku features
        clip_comments = [
            c for c in danmaku_data
            if start <= c.get("time_offset", 0) <= end
        ]
        density = len(clip_comments) / duration
        density_norm = min(density / 5.0, 1.0)

        # ASR features
        clip_segments = [
            s for s in segments_data
            if s.get("start", 0) < end and s.get("end", 0) > start
        ]
        speech_coverage = sum(
            min(s["end"], end) - max(s["start"], start)
            for s in clip_segments
        ) / duration if clip_segments else 0.0

        # Simple heuristic scoring (replace with ML model when trained)
        composite = (
            0.40 * density_norm +
            0.30 * min(speech_coverage, 1.0) +
            0.15 * min(len(clip_comments) / 50.0, 1.0) +
            0.15 * (0.5 if duration > 15 else 0.3)
        )
        composite = min(composite, 1.0)

        scores.append(ViralityScoreOut(
            composite=round(composite, 4),
            predicted_ctr=round(composite * 0.7, 4),
            predicted_share=round(composite * 0.4, 4),
        ))

    return ViralityResponse(scores=scores)
