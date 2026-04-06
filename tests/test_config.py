import pytest

from stream_clipper.config import PipelineConfig, resolve_clip_window


def test_pipeline_config_accepts_valid_weights() -> None:
    cfg = PipelineConfig(weights=(0.4, 0.4, 0.2))
    assert cfg.weights == (0.4, 0.4, 0.2)


def test_pipeline_config_rejects_invalid_weight_sum() -> None:
    with pytest.raises(ValueError):
        PipelineConfig(weights=(0.5, 0.5, 0.5))


def test_pipeline_config_rejects_negative_padding() -> None:
    with pytest.raises(ValueError):
        PipelineConfig(pad_before=-1.0)


def test_pipeline_config_rejects_invalid_candidate_multiplier() -> None:
    with pytest.raises(ValueError):
        PipelineConfig(candidate_multiplier=0)


def test_pipeline_config_rejects_invalid_half_peak_ratio() -> None:
    with pytest.raises(ValueError):
        PipelineConfig(half_peak_ratio=0.99)


def test_pipeline_config_rejects_invalid_llm_score_weight() -> None:
    with pytest.raises(ValueError):
        PipelineConfig(llm_score_weight=1.1)


def test_pipeline_config_rejects_non_positive_llm_timeout() -> None:
    with pytest.raises(ValueError):
        PipelineConfig(llm_timeout_sec=0)


def test_pipeline_config_rejects_invalid_semantic_score_weight() -> None:
    with pytest.raises(ValueError):
        PipelineConfig(semantic_score_weight=1.2)


def test_pipeline_config_rejects_non_positive_semantic_timeout() -> None:
    with pytest.raises(ValueError):
        PipelineConfig(semantic_timeout_sec=0)


def test_resolve_clip_window_defaults_follow_requested_clip_duration() -> None:
    window = resolve_clip_window(240)

    assert window["clip_duration"] == 240
    assert window["pad_before"] == pytest.approx(80.0)
    assert window["pad_after"] == pytest.approx(160.0)
    assert window["adaptive_max_before"] == pytest.approx(80.0)
    assert window["adaptive_max_after"] == pytest.approx(160.0)


def test_resolve_clip_window_preserves_explicit_adaptive_caps() -> None:
    window = resolve_clip_window(
        240,
        adaptive_min_before=5,
        adaptive_max_before=45,
        adaptive_min_after=8,
        adaptive_max_after=60,
    )

    assert window["adaptive_max_before"] == pytest.approx(45.0)
    assert window["adaptive_max_after"] == pytest.approx(60.0)
