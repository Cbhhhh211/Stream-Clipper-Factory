"""
yt-dlp runtime guard utilities.

Ensures the local yt-dlp binary exists and meets a minimum version so
download/record features don't silently break on extractor changes.
"""

from __future__ import annotations

import os
import re
import subprocess
from functools import lru_cache
from typing import Tuple


def _version_tuple(raw: str) -> Tuple[int, int, int]:
    s = (raw or "").strip()
    if not s:
        return (0, 0, 0)
    m = re.search(r"(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})", s)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    nums = re.findall(r"\d+", s)
    if len(nums) >= 3:
        return (int(nums[0]), int(nums[1]), int(nums[2]))
    return (0, 0, 0)


def _read_version() -> str:
    try:
        result = subprocess.run(
            ["yt-dlp", "--version"],
            capture_output=True,
            text=True,
            timeout=6,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "yt-dlp is not installed. Install with `pip install -U yt-dlp` "
            "or run `yt-dlp -U` if already installed."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("yt-dlp version check timed out. Please verify yt-dlp is executable.") from exc

    if result.returncode != 0:
        tail = (result.stderr or "").strip()[-400:]
        raise RuntimeError(
            "Failed to run `yt-dlp --version`. "
            f"stderr: {tail or '(empty)'}"
        )
    return (result.stdout or "").strip()


@lru_cache(maxsize=1)
def ensure_ytdlp_ready() -> str:
    """
    Validate yt-dlp availability + minimum version once per process.
    """
    current = _read_version()
    min_required = os.getenv("YTDLP_MIN_VERSION", "2025.01.15").strip() or "2025.01.15"
    current_t = _version_tuple(current)
    min_t = _version_tuple(min_required)

    if current_t < min_t:
        raise RuntimeError(
            "yt-dlp is too old for reliable Bilibili extraction. "
            f"Current={current}, required>={min_required}. "
            "Update with `yt-dlp -U` or `pip install -U yt-dlp`."
        )
    return current

