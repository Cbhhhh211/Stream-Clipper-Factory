"""
Shared utility helpers used across multiple modules.
"""

from __future__ import annotations

import json
import locale
import re
import subprocess
from pathlib import Path
from typing import Any, Optional


def safe_name(s: str, max_len: int = 60) -> str:
    """Sanitize a string for use as a filename component."""
    return re.sub(r"[^\w\-]", "_", s)[:max_len]


def safe_decode(data: bytes, preferred_encoding: Optional[str] = None) -> str:
    """
    Decode command output bytes robustly across OS locale differences.

    Falls back to UTF-8 and common Windows encodings, always returning text.
    """
    if not data:
        return ""

    candidates = []
    if preferred_encoding:
        candidates.append(preferred_encoding)
    sys_enc = locale.getpreferredencoding(False)
    if sys_enc:
        candidates.append(sys_enc)
    candidates.extend(["utf-8", "gbk", "cp936", "latin-1"])

    tried = set()
    for enc in candidates:
        if not enc or enc in tried:
            continue
        tried.add(enc)
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue

    # Last resort: never fail the caller on decoding
    return data.decode("utf-8", errors="replace")


def parse_bool(value: Any, default: bool = False) -> bool:
    """Parse mixed-type flags consistently across API and worker code."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def probe_duration(path: Path) -> float:
    """
    Return the duration of a media file in seconds via ffprobe.

    Returns 0.0 if the file cannot be probed (missing, corrupted, etc.).
    """
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(path),
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        return 0.0
