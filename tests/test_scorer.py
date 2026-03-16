import numpy as np

from stream_clipper.asr.transcriber import Segment
from stream_clipper.danmaku.models import DanmakuComment
from stream_clipper.resonance.scorer import compute_scores


def test_compute_scores_basic_range_and_signal() -> None:
    comments = [
        DanmakuComment(time_offset=9.8, text="卧槽太强了"),
        DanmakuComment(time_offset=10.2, text="666"),
        DanmakuComment(time_offset=10.7, text="笑死"),
    ]
    segments = [
        Segment(start=9.0, end=12.0, text="这波操作太强了"),
        Segment(start=20.0, end=22.0, text="普通叙述"),
    ]

    times, scores = compute_scores(comments, segments, duration=30, window=6.0)

    assert len(times) == 30
    assert len(scores) == 30
    assert np.all(scores >= 0.0)
    assert np.all(scores <= 1.0)
    assert scores[10] > scores[0]


def test_compute_scores_asr_only_path() -> None:
    comments = []
    segments = [
        Segment(start=4.0, end=7.0, text="这段太强了简直离谱"),
        Segment(start=15.0, end=16.0, text="平稳叙述"),
    ]

    times, scores = compute_scores(comments, segments, duration=20, window=6.0)

    assert len(times) == 20
    assert len(scores) == 20
    assert float(scores.max()) > 0.0


def test_compute_scores_prefers_burst_over_flat_density() -> None:
    comments = [
        DanmakuComment(time_offset=float(t) + 0.1, text=f"ok-{t}")
        for t in range(40)
    ]
    comments.extend(
        DanmakuComment(time_offset=50.0 + (i * 0.05), text="哈哈哈哈")
        for i in range(40)
    )

    segments = [Segment(start=0.0, end=90.0, text="普通叙述")]
    _times, scores = compute_scores(comments, segments, duration=90, window=10.0)

    assert float(scores[50]) > float(scores[20])


def test_compute_scores_sentiment_signal_lifts_positive_window() -> None:
    comments = []
    comments.extend(
        DanmakuComment(time_offset=10.0 + i * 0.2, text="封神 太强了 666")
        for i in range(8)
    )
    comments.extend(
        DanmakuComment(time_offset=30.0 + i * 0.2, text="普通 普通 普通")
        for i in range(8)
    )
    segments = [Segment(start=0.0, end=60.0, text="主播持续讲话")]

    _times, scores = compute_scores(comments, segments, duration=60, window=8.0)
    assert float(scores[10]) > float(scores[30])


def test_compute_scores_audio_energy_supports_asr_only_scoring() -> None:
    comments = []
    segments = [Segment(start=0.0, end=60.0, text="持续语音内容")]
    audio_energy = np.zeros(60, dtype=np.float64)
    audio_energy[30] = 1.0

    _times, scores = compute_scores(
        comments,
        segments,
        duration=60,
        window=8.0,
        audio_energy=audio_energy,
    )
    assert float(scores[30]) > float(scores[10])

