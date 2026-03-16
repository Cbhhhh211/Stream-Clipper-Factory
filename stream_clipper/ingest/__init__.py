from .base import IngestResult
from .local import LocalIngest
from .bili_vod import BiliVodIngest
from .bili_live import BiliLiveIngest
from .web_video import WebVodIngest, WebLiveIngest

__all__ = [
    "IngestResult",
    "LocalIngest",
    "BiliVodIngest",
    "BiliLiveIngest",
    "WebVodIngest",
    "WebLiveIngest",
]
