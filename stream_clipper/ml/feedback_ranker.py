"""
Feedback-driven ranking model for highlight quality.

This module trains and serves a lightweight linear model using user ratings
(`good` / `average` / `bad`) logged from review feedback.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import numpy as np

DEFAULT_FEATURE_KEYS = (
    "resonance_score",
    "log_danmaku_count",
    "keyword_count",
    "clip_duration",
    "adjustment_count",
    "abs_start_delta",
    "abs_end_delta",
    "abs_total_delta",
    "virality_score",
    "has_virality",
)


def rating_to_target(rating: str) -> Optional[float]:
    r = (rating or "").strip().lower()
    if r == "good":
        return 1.0
    if r == "average":
        return 0.5
    if r == "bad":
        return 0.0
    return None


def default_model_path() -> Path:
    configured = os.getenv("FEEDBACK_RANKER_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_absolute() else (Path.cwd() / path).resolve()
    return (Path(os.getenv("OUTPUT_DIR", "./output")) / "_api_jobs" / "_feedback" / "ranker_model.json").resolve()


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw:
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
    return rows


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def extract_features(record: Dict[str, Any]) -> Dict[str, float]:
    """Extract ranking features from feedback row or runtime highlight dict."""
    score = _to_float(record.get("highlight_score", record.get("score", 0.0)))
    danmaku_count = max(0.0, _to_float(record.get("danmaku_count", 0.0)))
    top_keywords = record.get("top_keywords", []) or []
    keyword_count = float(len(top_keywords) if isinstance(top_keywords, list) else 0)

    duration = _to_float(record.get("duration", 0.0), 0.0)
    if duration <= 0:
        start = _to_float(record.get("clip_start", record.get("start", 0.0)), 0.0)
        end = _to_float(record.get("clip_end", record.get("end", 0.0)), 0.0)
        duration = max(0.0, end - start)

    virality_raw = record.get("virality_score", None)
    has_virality = 0.0 if virality_raw is None else 1.0
    virality_score = _to_float(virality_raw, 0.0)

    # User-edit signals (from review adjustments).
    adjustments = max(
        0.0,
        _to_float(
            record.get("adjustments", record.get("adjustment_count", 0.0)),
            0.0,
        ),
    )
    start_delta = _to_float(
        record.get("delta_start_vs_ai", record.get("delta_start_vs_prev", 0.0)),
        0.0,
    )
    end_delta = _to_float(
        record.get("delta_end_vs_ai", record.get("delta_end_vs_prev", 0.0)),
        0.0,
    )
    abs_start_delta = abs(_to_float(record.get("abs_start_delta", start_delta), 0.0))
    abs_end_delta = abs(_to_float(record.get("abs_end_delta", end_delta), 0.0))

    return {
        "resonance_score": max(0.0, min(1.0, score)),
        "log_danmaku_count": float(np.log1p(danmaku_count)),
        "keyword_count": keyword_count,
        "clip_duration": duration,
        "adjustment_count": adjustments,
        "abs_start_delta": abs_start_delta,
        "abs_end_delta": abs_end_delta,
        "abs_total_delta": abs_start_delta + abs_end_delta,
        "virality_score": max(0.0, min(1.0, virality_score)),
        "has_virality": has_virality,
    }


def merge_feedback_with_adjustments(
    feedback_rows: List[Dict[str, Any]],
    adjustment_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Join adjustment signals into feedback rows using (job_id, clip_id).

    This lets the ranker learn not only from explicit ratings, but also from
    how much users tend to trim AI-generated boundaries.
    """
    by_clip: Dict[tuple[str, str], Dict[str, float]] = {}
    for row in adjustment_rows:
        if not isinstance(row, dict):
            continue
        clip_id = str(row.get("clip_id", "")).strip()
        job_id = str(row.get("job_id", "")).strip()
        if not clip_id:
            continue
        key = (job_id, clip_id)
        start_delta = _to_float(
            row.get("delta_start_vs_ai", row.get("delta_start_vs_prev", 0.0)),
            0.0,
        )
        end_delta = _to_float(
            row.get("delta_end_vs_ai", row.get("delta_end_vs_prev", 0.0)),
            0.0,
        )
        agg = by_clip.get(key)
        if agg is None:
            agg = {
                "count": 0.0,
                "sum_abs_start": 0.0,
                "sum_abs_end": 0.0,
                "last_start_delta": 0.0,
                "last_end_delta": 0.0,
            }
            by_clip[key] = agg
        agg["count"] += 1.0
        agg["sum_abs_start"] += abs(start_delta)
        agg["sum_abs_end"] += abs(end_delta)
        agg["last_start_delta"] = start_delta
        agg["last_end_delta"] = end_delta

    merged: List[Dict[str, Any]] = []
    for row in feedback_rows:
        if not isinstance(row, dict):
            continue
        rec = dict(row)
        clip_id = str(rec.get("clip_id", "")).strip()
        job_id = str(rec.get("job_id", "")).strip()
        if clip_id:
            agg = by_clip.get((job_id, clip_id))
            if agg:
                count = max(1.0, agg.get("count", 1.0))
                rec["adjustments"] = max(
                    _to_float(rec.get("adjustments", 0.0), 0.0),
                    agg.get("count", 0.0),
                )
                rec["delta_start_vs_ai"] = agg.get("last_start_delta", 0.0)
                rec["delta_end_vs_ai"] = agg.get("last_end_delta", 0.0)
                rec["abs_start_delta"] = agg.get("sum_abs_start", 0.0) / count
                rec["abs_end_delta"] = agg.get("sum_abs_end", 0.0) / count
        merged.append(rec)
    return merged


def _matrix_from_rows(rows: Iterable[Dict[str, Any]], feature_keys: Iterable[str]) -> np.ndarray:
    keys = list(feature_keys)
    x = [[extract_features(r).get(k, 0.0) for k in keys] for r in rows]
    return np.asarray(x, dtype=np.float64)


def train_feedback_model(
    rows: List[Dict[str, Any]],
    *,
    feature_keys: Iterable[str] = DEFAULT_FEATURE_KEYS,
    min_samples: int = 8,
    l2_alpha: float = 0.2,
) -> Dict[str, Any]:
    """
    Train a ridge-linear quality model from feedback rows.

    Returns a JSON-serializable model dictionary.
    """
    keys = list(feature_keys)
    filtered = [r for r in rows if rating_to_target(str(r.get("rating", ""))) is not None]
    if len(filtered) < min_samples:
        raise ValueError(f"Need at least {min_samples} valid feedback rows, got {len(filtered)}")

    x = _matrix_from_rows(filtered, keys)
    y = np.asarray(
        [rating_to_target(str(r.get("rating", ""))) for r in filtered],
        dtype=np.float64,
    )

    means = x.mean(axis=0)
    stds = x.std(axis=0)
    stds = np.where(stds < 1e-8, 1.0, stds)
    xn = (x - means) / stds

    n, d = xn.shape
    xb = np.hstack([xn, np.ones((n, 1), dtype=np.float64)])

    reg = np.eye(d + 1, dtype=np.float64) * float(max(0.0, l2_alpha))
    reg[-1, -1] = 0.0  # do not regularize bias
    params = np.linalg.solve(xb.T @ xb + reg, xb.T @ y)

    w = params[:-1]
    b = float(params[-1])
    pred = np.clip(xn @ w + b, 0.0, 1.0)

    mae = float(np.mean(np.abs(pred - y)))
    rmse = float(np.sqrt(np.mean((pred - y) ** 2)))
    if np.std(pred) < 1e-8 or np.std(y) < 1e-8:
        corr = 0.0
    else:
        corr = float(np.corrcoef(pred, y)[0, 1])

    return {
        "version": 1,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "n_samples": int(len(filtered)),
        "feature_keys": keys,
        "means": {k: float(means[i]) for i, k in enumerate(keys)},
        "stds": {k: float(stds[i]) for i, k in enumerate(keys)},
        "weights": {k: float(w[i]) for i, k in enumerate(keys)},
        "bias": b,
        "metrics": {
            "mae": round(mae, 6),
            "rmse": round(rmse, 6),
            "pearson_corr": round(corr, 6),
        },
    }


def load_feedback_model(path: Optional[Path | str] = None) -> Optional[Dict[str, Any]]:
    model_path = Path(path).expanduser() if path else default_model_path()
    if not model_path.is_absolute():
        model_path = (Path.cwd() / model_path).resolve()
    if not model_path.exists():
        return None
    try:
        obj = json.loads(model_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    if not isinstance(obj.get("feature_keys"), list):
        return None
    if not isinstance(obj.get("weights"), dict):
        return None
    if not isinstance(obj.get("means"), dict):
        return None
    if not isinstance(obj.get("stds"), dict):
        return None
    return obj


def save_feedback_model(model: Dict[str, Any], path: Optional[Path | str] = None) -> Path:
    model_path = Path(path).expanduser() if path else default_model_path()
    if not model_path.is_absolute():
        model_path = (Path.cwd() / model_path).resolve()
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_text(json.dumps(model, ensure_ascii=False, indent=2), encoding="utf-8")
    return model_path


def predict_quality(features: Dict[str, float], model: Dict[str, Any]) -> float:
    keys = [str(k) for k in model.get("feature_keys", [])]
    if not keys:
        return 0.0

    weights = model.get("weights", {})
    means = model.get("means", {})
    stds = model.get("stds", {})
    bias = _to_float(model.get("bias", 0.0))

    vec = []
    for k in keys:
        x = _to_float(features.get(k, 0.0), 0.0)
        mu = _to_float(means.get(k, 0.0), 0.0)
        sd = _to_float(stds.get(k, 1.0), 1.0)
        if abs(sd) < 1e-8:
            sd = 1.0
        vec.append((x - mu) / sd)

    w = np.asarray([_to_float(weights.get(k, 0.0), 0.0) for k in keys], dtype=np.float64)
    x = np.asarray(vec, dtype=np.float64)
    y = float(x @ w + bias)
    return float(max(0.0, min(1.0, y)))
