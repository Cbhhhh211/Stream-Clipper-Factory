"""Shared data container for all ingest sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from ..danmaku.models import DanmakuComment


@dataclass
class IngestResult:
    """Everything the pipeline needs after ingestion."""
    video_path: Path                          # local path to the video file
    comments: List[DanmakuComment]           # all danmaku comments
    duration: float                           # video duration in seconds
    title: str = ""                           # human-readable title for output naming
    source_url: Optional[str] = None
    is_temp: bool = False                     # if True, caller should delete video_path after use
