"""
Speech-to-text transcription using faster-whisper.

Supports auto device selection (CUDA > CPU), auto compute type, and a
module-level model cache so the same model is not reloaded between calls
(important for repeated use from the Gradio UI).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..logging import console


@dataclass
class Segment:
    """A single ASR output segment with start/end timestamps."""
    start: float
    end: float
    text: str

    def __repr__(self) -> str:
        return f"Segment({self.start:.1f}-{self.end:.1f}s: {self.text!r})"


# ---------------------------------------------------------------------------
# Model cache: keyed by (model_size, device, compute_type)
# ---------------------------------------------------------------------------
_MODEL_CACHE: Dict[Tuple[str, str, str], "WhisperModel"] = {}  # type: ignore[name-defined]


def _env_int(name: str, default: int, min_value: int = 1) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_value, value)


def _get_model(model_size: str, device: str, compute_type: str) -> "WhisperModel":  # type: ignore[name-defined]
    """Return a cached WhisperModel, loading it on first use."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise ImportError(
            "faster-whisper is not installed. Run: pip install faster-whisper"
        ) from None

    key = (model_size, device, compute_type)
    if key not in _MODEL_CACHE:
        console.print(
            f"[dim]Loading Whisper model '{model_size}' on {device} ({compute_type})...[/dim]"
        )
        _MODEL_CACHE[key] = WhisperModel(model_size, device=device, compute_type=compute_type)
    return _MODEL_CACHE[key]


def transcribe(
    audio_path: str,
    model_size: str = "base",
    language: Optional[str] = "zh",
    device: Optional[str] = None,
    compute_type: Optional[str] = None,
) -> List[Segment]:
    """
    Transcribe audio to a list of Segments using faster-whisper.

    The WhisperModel is cached after the first call for (model_size, device,
    compute_type) so repeated invocations (e.g. from the Gradio UI) do not
    pay the model-load cost.

    Args:
        audio_path:   Path to WAV/MP3/etc audio file.
        model_size:   Whisper model variant: tiny/base/small/medium/large-v2/large-v3.
        language:     BCP-47 language code or None for auto-detect.
                      Use "zh" for Mandarin, None for multilingual streams.
        device:       "cuda" / "cpu" / None (auto-detect).
        compute_type: "float16" / "int8" / "float32" / None (auto).

    Returns:
        List of Segment objects sorted by start time.
    """
    if device is None:
        device = _auto_device()
    if compute_type is None:
        compute_type = "float16" if device == "cuda" else "int8"

    model = _get_model(model_size, device, compute_type)
    beam_size = _env_int("ASR_BEAM_SIZE", 1, min_value=1)
    vad_min_silence_ms = _env_int("ASR_VAD_MIN_SILENCE_MS", 1000, min_value=100)

    console.print(f"[dim]Transcribing {os.path.basename(audio_path)}...[/dim]")
    gen, info = model.transcribe(
        audio_path,
        language=language,
        beam_size=beam_size,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": vad_min_silence_ms},
    )

    segments: List[Segment] = []
    for seg in gen:
        text = seg.text.strip()
        if text:
            segments.append(Segment(start=seg.start, end=seg.end, text=text))

    console.print(
        f"[green]Transcribed {len(segments)} segments "
        f"(detected language: {info.language}, "
        f"probability: {info.language_probability:.0%})[/green]"
    )
    return segments


def _auto_device() -> str:
    """Return 'cuda' if a CUDA GPU is available, else 'cpu'."""
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
