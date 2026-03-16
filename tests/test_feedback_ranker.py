import json
from pathlib import Path
from uuid import uuid4

import pytest

from stream_clipper.ml.feedback_ranker import (
    extract_features,
    load_feedback_model,
    merge_feedback_with_adjustments,
    predict_quality,
    save_feedback_model,
    train_feedback_model,
)


def _sample_rows():
    return [
        {
            "clip_id": "c1",
            "job_id": "j1",
            "rating": "good",
            "score": 0.82,
            "danmaku_count": 320,
            "top_keywords": ["wow", "lol", "insane"],
            "duration": 35,
            "virality_score": 0.76,
        },
        {
            "clip_id": "c2",
            "job_id": "j1",
            "rating": "good",
            "score": 0.73,
            "danmaku_count": 260,
            "top_keywords": ["nice", "clean"],
            "duration": 30,
            "virality_score": 0.68,
        },
        {
            "clip_id": "c3",
            "job_id": "j1",
            "rating": "average",
            "score": 0.55,
            "danmaku_count": 120,
            "top_keywords": ["ok"],
            "duration": 32,
            "virality_score": 0.45,
        },
        {
            "clip_id": "c4",
            "job_id": "j2",
            "rating": "average",
            "score": 0.48,
            "danmaku_count": 80,
            "top_keywords": [],
            "duration": 28,
            "virality_score": 0.35,
        },
        {
            "clip_id": "c5",
            "job_id": "j2",
            "rating": "bad",
            "score": 0.21,
            "danmaku_count": 12,
            "top_keywords": [],
            "duration": 30,
            "virality_score": 0.11,
        },
        {
            "clip_id": "c6",
            "job_id": "j2",
            "rating": "bad",
            "score": 0.15,
            "danmaku_count": 6,
            "top_keywords": [],
            "duration": 25,
            "virality_score": 0.08,
        },
    ]


def test_train_feedback_model_requires_min_samples() -> None:
    with pytest.raises(ValueError):
        train_feedback_model(_sample_rows()[:2], min_samples=5)


def test_train_and_predict_quality_ordering() -> None:
    rows = _sample_rows()
    model = train_feedback_model(rows, min_samples=4, l2_alpha=0.1)

    good_features = extract_features(rows[0])
    bad_features = extract_features(rows[-1])
    good_pred = predict_quality(good_features, model)
    bad_pred = predict_quality(bad_features, model)

    assert 0.0 <= good_pred <= 1.0
    assert 0.0 <= bad_pred <= 1.0
    assert good_pred > bad_pred


def test_save_and_load_feedback_model() -> None:
    model = train_feedback_model(_sample_rows(), min_samples=4, l2_alpha=0.2)
    temp_dir = Path("output") / "_test_tmp_ranker" / uuid4().hex
    temp_dir.mkdir(parents=True, exist_ok=True)
    model_path = temp_dir / "ranker_model.json"
    save_feedback_model(model, model_path)

    loaded = load_feedback_model(model_path)
    assert loaded is not None
    assert loaded["n_samples"] == model["n_samples"]
    assert loaded["feature_keys"] == model["feature_keys"]

    data = json.loads(model_path.read_text(encoding="utf-8"))
    assert "weights" in data


def test_merge_feedback_with_adjustments_enriches_rows() -> None:
    feedback_rows = _sample_rows()[:2]
    adjustment_rows = [
        {
            "clip_id": "c1",
            "job_id": "j1",
            "delta_start_vs_ai": -1.5,
            "delta_end_vs_ai": 2.0,
        },
        {
            "clip_id": "c1",
            "job_id": "j1",
            "delta_start_vs_ai": -0.5,
            "delta_end_vs_ai": 1.0,
        },
        {
            "clip_id": "c2",
            "job_id": "j1",
            "delta_start_vs_prev": -2.0,
            "delta_end_vs_prev": 0.5,
        },
    ]

    merged = merge_feedback_with_adjustments(feedback_rows, adjustment_rows)
    assert len(merged) == 2

    row1 = next(r for r in merged if r["clip_id"] == "c1")
    assert row1["adjustments"] == 2
    assert abs(float(row1["abs_start_delta"]) - 1.0) < 1e-9
    assert abs(float(row1["abs_end_delta"]) - 1.5) < 1e-9

    row2 = next(r for r in merged if r["clip_id"] == "c2")
    assert row2["adjustments"] == 1
    assert abs(float(row2["delta_start_vs_ai"]) - (-2.0)) < 1e-9
    assert abs(float(row2["delta_end_vs_ai"]) - 0.5) < 1e-9

