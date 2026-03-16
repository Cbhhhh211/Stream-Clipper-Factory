"""Ingest from a local video file with an optional danmaku XML."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from ..danmaku.models import DanmakuComment
from ..danmaku.parser import parse_xml
from ..utils import probe_duration
from .base import IngestResult


def _probe_duration(video_path: Path) -> float:
    """Thin wrapper kept for backward-compat with bili_vod/bili_live imports."""
    dur = probe_duration(video_path)
    if dur == 0.0:
        raise RuntimeError(f"ffprobe failed or returned 0 for: {video_path}")
    return dur


class LocalIngest:
    """
    Ingest a local video file.

    Args:
        video_path:   Path to the video file (MP4, MKV, FLV, …).
        danmaku_path: Path to the Bilibili XML danmaku file (optional).
    """

    def __init__(self, video_path: str, danmaku_path: Optional[str] = None):
        self.video_path = Path(video_path)
        self.danmaku_path = Path(danmaku_path) if danmaku_path else None

    def run(self) -> IngestResult:
        if not self.video_path.exists():
            raise FileNotFoundError(f"Video file not found: {self.video_path}")

        duration = _probe_duration(self.video_path)

        comments: List[DanmakuComment] = []
        if self.danmaku_path:
            if not self.danmaku_path.exists():
                raise FileNotFoundError(f"Danmaku file not found: {self.danmaku_path}")
            comments = parse_xml(str(self.danmaku_path))

        return IngestResult(
            video_path=self.video_path,
            comments=comments,
            duration=duration,
            title=self.video_path.stem,
            is_temp=False,
        )
