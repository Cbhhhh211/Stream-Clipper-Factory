"""
Central pipeline configuration.

All tunable parameters live here so callers pass one object instead of
many keyword arguments across the call stack.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


def resolve_clip_window(
    clip_duration: float,
    *,
    adaptive_min_before: float = 5.0,
    adaptive_max_before: Optional[float] = None,
    adaptive_min_after: float = 8.0,
    adaptive_max_after: Optional[float] = None,
) -> dict[str, float]:
    """
    Derive fixed padding plus adaptive bounds from the requested clip duration.

    When callers do not provide adaptive max bounds, we keep the historical
    1/3-before, 2/3-after ratio so the requested clip duration remains the
    effective target length even with adaptive padding enabled.
    """
    normalized_duration = max(5.0, min(3600.0, float(clip_duration)))
    pad_before = normalized_duration / 3.0
    pad_after = normalized_duration - pad_before

    min_before = max(0.0, float(adaptive_min_before))
    min_after = max(0.0, float(adaptive_min_after))

    if adaptive_max_before is None:
        adaptive_max_before = pad_before
    if adaptive_max_after is None:
        adaptive_max_after = pad_after

    max_before = max(min_before, min(3600.0, float(adaptive_max_before)))
    max_after = max(min_after, min(3600.0, float(adaptive_max_after)))

    return {
        "clip_duration": normalized_duration,
        "pad_before": pad_before,
        "pad_after": pad_after,
        "adaptive_min_before": min_before,
        "adaptive_max_before": max_before,
        "adaptive_min_after": min_after,
        "adaptive_max_after": max_after,
    }


@dataclass
class PipelineConfig:
    # ASR
    model_size: str = "base"
    language: Optional[str] = "zh"

    # Resonance scoring
    weights: Tuple[float, float, float] = (0.4, 0.4, 0.2)
    window: float = 10.0

    # Peak detection
    top_n: int = 10
    candidate_multiplier: int = 3
    pad_before: float = 15.0
    pad_after: float = 30.0
    min_gap: float = 60.0
    threshold: Optional[float] = None  # None means auto (mean + 1 sigma)
    adaptive_padding: bool = True
    half_peak_ratio: float = 0.5
    adaptive_min_before: float = 5.0
    adaptive_max_before: float = 45.0
    adaptive_min_after: float = 8.0
    adaptive_max_after: float = 60.0

    # Feedback-driven ranking
    enable_feedback_ranking: bool = True
    feedback_model_path: Optional[str] = None
    enable_llm_rerank: Optional[bool] = None
    llm_model: Optional[str] = None
    llm_max_candidates: int = 20
    llm_score_weight: float = 0.65
    llm_timeout_sec: float = 30.0
    enable_semantic_enrichment: Optional[bool] = None
    semantic_model: Optional[str] = None
    semantic_max_candidates: int = 8
    semantic_score_weight: float = 0.2
    semantic_timeout_sec: float = 30.0

    # Boundary adaptation from user trim adjustments
    enable_boundary_adaptation: bool = True
    boundary_profile_path: Optional[str] = None

    # Output
    save_scores: bool = True
    reencode_threshold: float = 2.0  # above this, re-encode for accuracy

    def __post_init__(self) -> None:
        w_sum = sum(self.weights)
        if abs(w_sum - 1.0) > 1e-6:
            raise ValueError(
                f"Resonance weights must sum to 1.0, got {w_sum:.4f} "
                f"(weights={self.weights})"
            )
        if self.pad_before < 0 or self.pad_after < 0:
            raise ValueError("pad_before and pad_after must be non-negative")
        if self.min_gap < 0:
            raise ValueError("min_gap must be non-negative")
        if self.candidate_multiplier < 1:
            raise ValueError("candidate_multiplier must be >= 1")
        if not 0.05 <= self.half_peak_ratio <= 0.95:
            raise ValueError("half_peak_ratio must be in [0.05, 0.95]")
        if self.adaptive_max_before < self.adaptive_min_before:
            raise ValueError("adaptive_max_before must be >= adaptive_min_before")
        if self.adaptive_max_after < self.adaptive_min_after:
            raise ValueError("adaptive_max_after must be >= adaptive_min_after")
        if self.llm_max_candidates < 1:
            raise ValueError("llm_max_candidates must be >= 1")
        if not 0.0 <= self.llm_score_weight <= 1.0:
            raise ValueError("llm_score_weight must be in [0, 1]")
        if self.llm_timeout_sec <= 0:
            raise ValueError("llm_timeout_sec must be > 0")
        if self.semantic_max_candidates < 1:
            raise ValueError("semantic_max_candidates must be >= 1")
        if not 0.0 <= self.semantic_score_weight <= 1.0:
            raise ValueError("semantic_score_weight must be in [0, 1]")
        if self.semantic_timeout_sec <= 0:
            raise ValueError("semantic_timeout_sec must be > 0")
