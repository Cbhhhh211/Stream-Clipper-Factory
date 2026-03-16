"""
Audio feature extraction utilities.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def _pcm_to_float32(samples: np.ndarray, sample_width: int) -> np.ndarray:
    if sample_width == 1:
        # 8-bit PCM is unsigned.
        return (samples.astype(np.float32) - 128.0) / 128.0
    if sample_width == 2:
        return samples.astype(np.float32) / 32768.0
    if sample_width == 4:
        return samples.astype(np.float32) / 2147483648.0
    raise ValueError(f"Unsupported WAV sample width: {sample_width} bytes")


def compute_rms_energy_per_second(audio_path: str | Path) -> np.ndarray:
    """
    Compute per-second RMS energy from a mono/stereo WAV file.

    Returns a float64 numpy array with one value per second.
    """
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")

    with wave.open(str(path), "rb") as wf:
        n_channels = int(wf.getnchannels())
        sample_width = int(wf.getsampwidth())
        sample_rate = int(wf.getframerate())
        n_frames = int(wf.getnframes())
        raw = wf.readframes(n_frames)

    if sample_rate <= 0:
        raise ValueError("Invalid sample rate in WAV")

    dtype_map = {1: np.uint8, 2: np.int16, 4: np.int32}
    dtype = dtype_map.get(sample_width)
    if dtype is None:
        raise ValueError(f"Unsupported WAV sample width: {sample_width} bytes")

    samples = np.frombuffer(raw, dtype=dtype)
    if samples.size == 0:
        return np.zeros(1, dtype=np.float64)

    if n_channels > 1:
        usable = (samples.size // n_channels) * n_channels
        samples = samples[:usable].reshape(-1, n_channels).mean(axis=1)

    signal = _pcm_to_float32(samples, sample_width)

    # One RMS bucket per second.
    bucket = max(1, sample_rate)
    pad = (-len(signal)) % bucket
    if pad > 0:
        signal = np.pad(signal, (0, pad), mode="constant")

    frames = signal.reshape(-1, bucket)
    rms = np.sqrt(np.mean(frames * frames, axis=1, dtype=np.float64))

    # Light smoothing to suppress click-level spikes.
    if rms.size >= 3:
        kernel = np.array([0.25, 0.5, 0.25], dtype=np.float64)
        rms = np.convolve(rms, kernel, mode="same")

    return np.asarray(rms, dtype=np.float64)

