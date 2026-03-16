"""
Model registry — manages lifecycle of ML models on GPU.

Supports:
  - faster-whisper (ASR)
  - Extensible for sentiment, virality, and embedding models.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ModelRegistry:
    """Centralized model loading, caching, and lifecycle management."""

    def __init__(self):
        self._models: Dict[str, Any] = {}
        self._metadata: Dict[str, dict] = {}

    def load_whisper(self, model_size: str = "large-v3") -> None:
        """Load a faster-whisper model onto GPU."""
        if "whisper" in self._models:
            logger.info("Whisper model already loaded, skipping")
            return

        device = self._detect_device()
        compute_type = "float16" if device == "cuda" else "int8"

        try:
            from faster_whisper import WhisperModel
            model = WhisperModel(model_size, device=device, compute_type=compute_type)
            self._models["whisper"] = model
            self._metadata["whisper"] = {
                "model_size": model_size,
                "device": device,
                "compute_type": compute_type,
                "loaded": True,
            }
            logger.info("Loaded Whisper %s on %s (%s)", model_size, device, compute_type)
        except ImportError:
            logger.error("faster-whisper not installed")
            raise
        except Exception as e:
            logger.error("Failed to load Whisper: %s", e)
            raise

    def get(self, name: str) -> Any:
        """Retrieve a loaded model by name."""
        model = self._models.get(name)
        if model is None:
            raise KeyError(f"Model '{name}' is not loaded")
        return model

    def is_loaded(self, name: str) -> bool:
        return name in self._models

    def unload(self, name: str) -> None:
        """Unload a model and free GPU memory."""
        if name in self._models:
            del self._models[name]
            del self._metadata[name]
            logger.info("Unloaded model: %s", name)

            # Try to free GPU memory
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

    def unload_all(self) -> None:
        """Unload all models."""
        names = list(self._models.keys())
        for name in names:
            self.unload(name)

    def status(self) -> Dict[str, dict]:
        """Return status of all loaded models."""
        result = {}
        for name, meta in self._metadata.items():
            result[name] = {**meta}

        # GPU memory info
        try:
            import torch
            if torch.cuda.is_available():
                for i in range(torch.cuda.device_count()):
                    allocated = torch.cuda.memory_allocated(i) / 1024**3
                    total = torch.cuda.get_device_properties(i).total_mem / 1024**3
                    result[f"gpu:{i}"] = {
                        "allocated_gb": round(allocated, 2),
                        "total_gb": round(total, 2),
                        "utilization": round(allocated / total, 2) if total > 0 else 0,
                    }
        except ImportError:
            pass

        return result

    @staticmethod
    def _detect_device() -> str:
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            pass
        try:
            import ctranslate2
            return "cuda" if "cuda" in ctranslate2.get_supported_compute_types("cuda") else "cpu"
        except Exception:
            pass
        return "cpu"
