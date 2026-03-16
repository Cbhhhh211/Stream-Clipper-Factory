"""
Boundary adaptation from user clip adjustments.

This module keeps a lightweight running profile of how users adjust
AI-generated clip boundaries (start/end deltas), then applies the learned
bias to future clips.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def default_boundary_profile_path() -> Path:
    configured = os.getenv("BOUNDARY_PROFILE_PATH", "").strip()
    if configured:
        p = Path(configured).expanduser()
        return p if p.is_absolute() else (Path.cwd() / p).resolve()
    return (Path(os.getenv("OUTPUT_DIR", "./output")) / "_api_jobs" / "_feedback" / "boundary_profile.json").resolve()


def _default_profile() -> Dict[str, Any]:
    return {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": 0,
        "mean_start_delta": 0.0,
        "mean_end_delta": 0.0,
    }


def load_boundary_profile(path: Optional[Path | str] = None) -> Dict[str, Any]:
    p = Path(path).expanduser() if path else default_boundary_profile_path()
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    if not p.exists():
        return _default_profile()
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return _default_profile()
    if not isinstance(obj, dict):
        return _default_profile()
    profile = _default_profile()
    profile.update(obj)
    return profile


def save_boundary_profile(profile: Dict[str, Any], path: Optional[Path | str] = None) -> Path:
    p = Path(path).expanduser() if path else default_boundary_profile_path()
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    out = dict(profile)
    out["updated_at"] = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def update_boundary_profile(
    start_delta: float,
    end_delta: float,
    *,
    path: Optional[Path | str] = None,
    max_abs_delta: float = 20.0,
    min_effective_delta: float = 0.3,
) -> Dict[str, Any]:
    """
    Update running means from one user adjustment.

    `start_delta = new_start - ai_start`, `end_delta = new_end - ai_end`
    """
    sd = float(max(-max_abs_delta, min(max_abs_delta, start_delta)))
    ed = float(max(-max_abs_delta, min(max_abs_delta, end_delta)))
    if abs(sd) < min_effective_delta and abs(ed) < min_effective_delta:
        return load_boundary_profile(path)

    profile = load_boundary_profile(path)
    n = int(profile.get("count", 0))
    m_start = float(profile.get("mean_start_delta", 0.0))
    m_end = float(profile.get("mean_end_delta", 0.0))

    new_n = n + 1
    profile["count"] = new_n
    profile["mean_start_delta"] = (m_start * n + sd) / new_n
    profile["mean_end_delta"] = (m_end * n + ed) / new_n
    save_boundary_profile(profile, path)
    return profile


def learned_deltas(
    profile: Dict[str, Any],
    *,
    min_samples: int = 3,
    max_apply_delta: float = 8.0,
) -> Tuple[float, float]:
    n = int(profile.get("count", 0))
    if n < min_samples:
        return 0.0, 0.0
    s = float(profile.get("mean_start_delta", 0.0))
    e = float(profile.get("mean_end_delta", 0.0))
    s = max(-max_apply_delta, min(max_apply_delta, s))
    e = max(-max_apply_delta, min(max_apply_delta, e))
    return s, e


def apply_boundary_adaptation(
    clip_start: float,
    clip_end: float,
    *,
    video_duration: float,
    profile: Dict[str, Any],
    min_duration: float = 5.0,
) -> Tuple[float, float]:
    """Apply learned global start/end deltas to one clip."""
    start_shift, end_shift = learned_deltas(profile)
    if start_shift == 0.0 and end_shift == 0.0:
        return clip_start, clip_end

    new_start = max(0.0, clip_start + start_shift)
    new_end = min(video_duration, clip_end + end_shift)
    if new_end - new_start < min_duration:
        # Expand around center to satisfy minimum clip length.
        center = (new_start + new_end) / 2.0
        half = min_duration / 2.0
        new_start = max(0.0, center - half)
        new_end = min(video_duration, center + half)
        if new_end - new_start < min_duration:
            if new_start <= 0:
                new_end = min(video_duration, min_duration)
            elif new_end >= video_duration:
                new_start = max(0.0, video_duration - min_duration)
    return float(new_start), float(new_end)
