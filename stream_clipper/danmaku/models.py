from dataclasses import dataclass


@dataclass
class DanmakuComment:
    """A single danmaku (bullet comment) with a time offset in seconds."""
    time_offset: float   # seconds from video start
    text: str
    user_id: str = ""
    dtype: int = 1       # 1=scrolling, 4=bottom, 5=top

    def __repr__(self) -> str:
        return f"DanmakuComment(t={self.time_offset:.1f}s, text={self.text!r})"
