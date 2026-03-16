import pytest

from stream_clipper.config import PipelineConfig


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
