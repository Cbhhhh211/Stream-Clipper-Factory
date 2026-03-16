import numpy as np

from stream_clipper.danmaku.models import DanmakuComment
from stream_clipper.resonance.peaks import find_highlights


def test_find_highlights_returns_sorted_clips_with_bounds() -> None:
    times = np.arange(100, dtype=np.float64) + 0.5
    scores = np.zeros(100, dtype=np.float64)
    scores[20] = 0.95
    scores[70] = 0.85

    comments = [
        DanmakuComment(time_offset=19.5, text="卧槽"),
        DanmakuComment(time_offset=20.2, text="666"),
        DanmakuComment(time_offset=70.1, text="绝了"),
    ]

    highlights = find_highlights(
        times=times,
        scores=scores,
        comments=comments,
        top_n=2,
        pad_before=5.0,
        pad_after=10.0,
        min_gap=20.0,
        threshold=0.3,
        sigma=1.0,
        video_duration=80.0,
    )

    assert len(highlights) == 2
    assert highlights[0].clip_start <= highlights[1].clip_start
    assert highlights[-1].clip_end <= 80.0
    assert highlights[0].duration > 0


def test_find_highlights_adaptive_padding_changes_duration() -> None:
    times = np.arange(120, dtype=np.float64) + 0.5
    scores = np.zeros(120, dtype=np.float64)
    # Wide hump peak
    for i in range(50, 70):
        scores[i] = 0.7
    scores[60] = 0.95

    comments = [DanmakuComment(time_offset=float(t), text="666") for t in range(48, 74)]

    fixed = find_highlights(
        times=times,
        scores=scores,
        comments=comments,
        top_n=1,
        pad_before=5.0,
        pad_after=5.0,
        min_gap=20.0,
        threshold=0.3,
        sigma=1.0,
        adaptive_padding=False,
    )
    adaptive = find_highlights(
        times=times,
        scores=scores,
        comments=comments,
        top_n=1,
        pad_before=5.0,
        pad_after=5.0,
        min_gap=20.0,
        threshold=0.3,
        sigma=1.0,
        adaptive_padding=True,
        half_peak_ratio=0.5,
    )

    assert len(fixed) == 1
    assert len(adaptive) == 1
    assert adaptive[0].duration >= fixed[0].duration
