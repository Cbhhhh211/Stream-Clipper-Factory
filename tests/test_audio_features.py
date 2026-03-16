import shutil
import wave
from pathlib import Path
from uuid import uuid4

import numpy as np

from stream_clipper.audio_features import compute_rms_energy_per_second


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int = 16000) -> None:
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def test_compute_rms_energy_per_second_detects_louder_second() -> None:
    sr = 16000
    t = np.linspace(0, 1.0, sr, endpoint=False)
    sec1 = 0.05 * np.sin(2 * np.pi * 440 * t)
    sec2 = 0.80 * np.sin(2 * np.pi * 440 * t)
    samples = np.concatenate([sec1, sec2])

    temp_dir = Path("output") / "_test_tmp_audio" / uuid4().hex
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        wav_path = temp_dir / "test.wav"
        _write_wav(wav_path, samples, sr)
        energy = compute_rms_energy_per_second(wav_path)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    assert energy.shape[0] == 2
    assert float(energy[1]) > float(energy[0])
