"""
Shared Rich console.

Import this instead of creating a new Console() in each module so that
output stays ordered even during multi-threaded live recording.
"""

from __future__ import annotations

import io
import sys
from typing import TextIO

from rich.console import Console


def _safe_stdout() -> TextIO:
    """
    Return a UTF-8 safe text stream for Rich output.

    On Windows, default `gbk` stdout can fail on some unicode characters from
    external tools (yt-dlp/ffmpeg metadata). We force UTF-8 or replace-invalid
    behavior to avoid crashing pipeline jobs due to logging.
    """
    out = sys.stdout
    if hasattr(out, "reconfigure"):
        try:
            out.reconfigure(encoding="utf-8", errors="replace")
            return out
        except Exception:
            pass

    # Fallback for environments without reconfigure support.
    try:
        if hasattr(out, "buffer"):
            return io.TextIOWrapper(
                out.buffer,
                encoding="utf-8",
                errors="replace",
                line_buffering=True,
            )
    except Exception:
        pass
    return out


console = Console(file=_safe_stdout())
