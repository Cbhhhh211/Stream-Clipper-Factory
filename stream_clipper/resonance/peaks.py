"""
Peak detection and clip boundary computation.

Includes optional adaptive boundary sizing based on local peak width
(half-peak scanning) instead of only fixed pad_before/pad_after.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

from ..danmaku.models import DanmakuComment
from .keywords import EXCITEMENT_KEYWORDS


@dataclass
class Highlight:
    clip_start: float
    clip_end: float
    peak_time: float
    score: float
    danmaku_count: int
    top_keywords: List[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.clip_end - self.clip_start

    def __repr__(self) -> str:
        return (
            f"Highlight({self.clip_start:.0f}s-{self.clip_end:.0f}s, "
            f"score={self.score:.3f}, comments={self.danmaku_count})"
        )


def _adaptive_pads_from_half_peak(
    times: np.ndarray,
    smoothed: np.ndarray,
    peak_idx: int,
    *,
    half_peak_ratio: float,
    min_before: float,
    max_before: float,
    min_after: float,
    max_after: float,
) -> tuple[float, float]:
    peak_value = float(smoothed[peak_idx])
    half_value = peak_value * half_peak_ratio

    left = peak_idx
    while left > 0 and float(smoothed[left]) >= half_value:
        left -= 1
    right = peak_idx
    last_idx = len(smoothed) - 1
    while right < last_idx and float(smoothed[right]) >= half_value:
        right += 1

    peak_time = float(times[peak_idx])
    raw_before = max(0.0, peak_time - float(times[left]))
    raw_after = max(0.0, float(times[right]) - peak_time)

    pad_before = max(min_before, min(max_before, raw_before))
    pad_after = max(min_after, min(max_after, raw_after))
    return pad_before, pad_after


def find_highlights(
    times: np.ndarray,
    scores: np.ndarray,
    comments: List[DanmakuComment],
    *,
    top_n: int = 10,
    pad_before: float = 15.0,
    pad_after: float = 30.0,
    min_gap: float = 60.0,
    threshold: float | None = None,
    sigma: float = 5.0,
    video_duration: float | None = None,
    adaptive_padding: bool = True,
    half_peak_ratio: float = 0.5,
    adaptive_min_before: float = 5.0,
    adaptive_max_before: float = 45.0,
    adaptive_min_after: float = 8.0,
    adaptive_max_after: float = 60.0,
) -> List[Highlight]:
    if len(scores) == 0:
        return []

    smoothed = gaussian_filter1d(scores.astype(np.float64), sigma=sigma)

    if threshold is None:
        threshold = float(smoothed.mean() + 1.0 * smoothed.std())
        threshold = max(threshold, 0.15)

    step = float(times[1] - times[0]) if len(times) > 1 else 1.0
    min_distance_samples = max(1, int(min_gap / step))

    peaks, _props = find_peaks(
        smoothed,
        height=threshold,
        distance=min_distance_samples,
        prominence=0.05,
    )
    if len(peaks) == 0:
        return []

    peak_scores = smoothed[peaks]
    order = np.argsort(peak_scores)[::-1]
    selected_peaks = peaks[order[:top_n]]

    comment_times = np.array([c.time_offset for c in comments], dtype=np.float64)

    highlights: List[Highlight] = []
    for idx in selected_peaks:
        peak_time = float(times[idx])
        score = float(smoothed[idx])

        local_before = pad_before
        local_after = pad_after
        if adaptive_padding:
            local_before, local_after = _adaptive_pads_from_half_peak(
                times,
                smoothed,
                int(idx),
                half_peak_ratio=max(0.1, min(0.9, half_peak_ratio)),
                min_before=max(0.0, adaptive_min_before),
                max_before=max(max(0.0, adaptive_min_before), adaptive_max_before),
                min_after=max(0.0, adaptive_min_after),
                max_after=max(max(0.0, adaptive_min_after), adaptive_max_after),
            )

        clip_start = max(0.0, peak_time - local_before)
        clip_end = peak_time + local_after
        if video_duration is not None:
            clip_end = min(clip_end, float(video_duration))
        if clip_end <= clip_start:
            continue

        mask = (comment_times >= clip_start) & (comment_times <= clip_end)
        window_idx = np.where(mask)[0]
        window_texts = [comments[j].text for j in window_idx]

        kw_counts: dict[str, int] = {}
        for text in window_texts:
            for kw in EXCITEMENT_KEYWORDS:
                if kw in text:
                    kw_counts[kw] = kw_counts.get(kw, 0) + 1
        top_keywords = sorted(kw_counts, key=kw_counts.get, reverse=True)[:5]

        highlights.append(
            Highlight(
                clip_start=clip_start,
                clip_end=clip_end,
                peak_time=peak_time,
                score=score,
                danmaku_count=int(len(window_idx)),
                top_keywords=top_keywords,
            )
        )

    highlights.sort(key=lambda h: h.clip_start)
    return highlights


def auto_threshold(scores: np.ndarray, sigma: float = 5.0) -> float:
    smoothed = gaussian_filter1d(scores.astype(np.float64), sigma=sigma)
    return float(max(smoothed.mean() + 1.0 * smoothed.std(), 0.15))
