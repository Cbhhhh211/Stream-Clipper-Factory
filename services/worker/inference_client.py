"""
HTTP client for communicating with the GPU inference service.

The worker (CPU) calls this client to offload ASR and ML model inference
to the dedicated GPU service.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Inference requests can be slow (large audio files)
DEFAULT_TIMEOUT = float(os.getenv("INFERENCE_TIMEOUT_SEC", "600"))  # 10 minutes
DEFAULT_RETRIES = int(os.getenv("INFERENCE_RETRIES", "2"))


class InferenceError(Exception):
    """Raised when the inference service returns an error."""
    pass


class InferenceClient:
    """HTTP client for the GPU inference service."""

    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(timeout=DEFAULT_TIMEOUT)
        self.retries = max(0, DEFAULT_RETRIES)

    def _post_json(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST JSON with bounded retry for transient network/service errors."""
        last_err: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            try:
                resp = self.client.post(f"{self.base_url}{path}", json=payload)
            except httpx.HTTPError as exc:
                last_err = exc
                if attempt < self.retries:
                    backoff = min(8.0, 1.6 ** attempt)
                    logger.warning(
                        "Inference request error (attempt %d/%d, path=%s): %s; retry in %.1fs",
                        attempt + 1,
                        self.retries + 1,
                        path,
                        exc,
                        backoff,
                    )
                    time.sleep(backoff)
                    continue
                raise InferenceError(f"Inference request failed: {exc}") from exc

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code >= 500 and attempt < self.retries:
                backoff = min(8.0, 1.6 ** attempt)
                logger.warning(
                    "Inference server error (attempt %d/%d, path=%s, status=%d); retry in %.1fs",
                    attempt + 1,
                    self.retries + 1,
                    path,
                    resp.status_code,
                    backoff,
                )
                time.sleep(backoff)
                continue

            raise InferenceError(
                f"Inference call failed ({resp.status_code}) at {path}: {resp.text[:500]}"
            )

        raise InferenceError(f"Inference request failed after retries: {last_err}")

    def health(self) -> dict:
        """Check inference service health."""
        resp = self.client.get(f"{self.base_url}/health")
        resp.raise_for_status()
        return resp.json()

    def transcribe(
        self,
        audio_s3_key: str,
        language: str = "zh",
        model_size: str = "large-v3",
    ) -> List[Dict[str, Any]]:
        """
        Send audio to inference service for ASR transcription.

        Args:
            audio_s3_key: S3 key where the audio WAV is stored.
            language: BCP-47 language code.
            model_size: Whisper model variant.

        Returns:
            List of segment dicts: [{"start": float, "end": float, "text": str}, ...]
        """
        data = self._post_json(
            "/v1/transcribe",
            {
                "audio_s3_key": audio_s3_key,
                "language": language,
                "model_size": model_size,
            },
        )
        segments = data.get("segments", [])
        logger.info("ASR returned %d segments", len(segments))
        return segments

    def predict_virality(
        self,
        segments_s3_key: str,
        danmaku_s3_key: str,
        highlights: List[Dict[str, float]],
    ) -> List[Dict[str, float]]:
        """
        Get virality predictions for a list of highlight windows.

        Args:
            segments_s3_key: S3 key for ASR segments JSON.
            danmaku_s3_key: S3 key for danmaku comments JSON.
            highlights: List of {"start": float, "end": float}.

        Returns:
            List of {"composite": float, "predicted_ctr": float, "predicted_share": float}.
        """
        data = self._post_json(
            "/v1/virality",
            {
                "segments_s3_key": segments_s3_key,
                "danmaku_s3_key": danmaku_s3_key,
                "highlights": highlights,
            },
        )
        scores = data.get("scores", [])
        logger.info("Virality predictions for %d highlights", len(scores))
        return scores

    def close(self) -> None:
        self.client.close()
