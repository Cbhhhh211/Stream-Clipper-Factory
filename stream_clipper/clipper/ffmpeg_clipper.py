"""
Video clip extraction using ffmpeg-python.

All clips are exported in compatibility-first format:
  - Video: H.264 (libx264) + yuv420p
  - Audio: AAC
  - Container: MP4 (+faststart)

This avoids AV1/HEVC playback issues in default system players.
"""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Optional, Tuple

import ffmpeg

from ..logging import console
from ..resonance.peaks import Highlight
from ..utils import safe_decode, safe_name


def _env_int(name: str, default: int, min_value: int, max_value: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        val = int(raw)
    except ValueError:
        return default
    return max(min_value, min(max_value, val))


def _encode_options() -> Tuple[str, int, str]:
    preset = os.getenv("CLIP_FFMPEG_PRESET", "ultrafast").strip() or "ultrafast"
    crf = _env_int("CLIP_FFMPEG_CRF", 23, min_value=15, max_value=40)
    audio_bitrate = os.getenv("CLIP_FFMPEG_AUDIO_BITRATE", "160k").strip() or "160k"
    return preset, crf, audio_bitrate


def _workers(total: int) -> int:
    if total <= 1:
        return 1
    cpu = os.cpu_count() or 1
    default_workers = min(4, max(1, cpu))
    configured = _env_int("CLIP_FFMPEG_WORKERS", default_workers, min_value=1, max_value=16)
    return min(total, configured)


def _cut_reencode(
    video_path: Path,
    start: float,
    duration: float,
    output_path: Path,
    *,
    preset: str,
    crf: int,
    audio_bitrate: str,
) -> bool:
    """Encode clip as H.264/AAC for broad player compatibility."""
    try:
        (
            ffmpeg
            .input(str(video_path), ss=start, t=duration)
            .output(
                str(output_path),
                vcodec="libx264",
                acodec="aac",
                pix_fmt="yuv420p",
                movflags="+faststart",
                crf=crf,
                preset=preset,
                audio_bitrate=audio_bitrate,
            )
            .overwrite_output()
            .run(quiet=True)
        )
        return True
    except ffmpeg.Error as e:
        console.print(f"[red]ffmpeg encode failed: {safe_decode(e.stderr)[-500:]}[/red]")
        return False


def _render_one_clip(
    idx: int,
    h: Highlight,
    video_path: Path,
    output_dir: Path,
    safe_title: str,
    *,
    preset: str,
    crf: int,
    audio_bitrate: str,
) -> Tuple[int, Optional[Path], str]:
    start = h.clip_start
    duration = h.duration
    score_str = f"{h.score:.2f}".replace(".", "")
    t_str = f"{int(h.peak_time):05d}"
    out_name = f"{safe_title}_highlight_{idx + 1:02d}_t{t_str}_s{score_str}.mp4"
    out_path = output_dir / out_name
    tmp_path = output_dir / f"_tmp_{uuid.uuid4().hex[:8]}_{out_name}"

    try:
        success = _cut_reencode(
            video_path,
            start,
            duration,
            tmp_path,
            preset=preset,
            crf=crf,
            audio_bitrate=audio_bitrate,
        )
        if success and tmp_path.exists():
            tmp_path.replace(out_path)
            kw_str = ", ".join(h.top_keywords[:3]) or "-"
            msg = (
                f"  [green][OK][/green] Clip {idx + 1}: "
                f"[white]{h.clip_start:.0f}s-{h.clip_end:.0f}s[/white]  "
                f"score=[magenta]{h.score:.3f}[/magenta]  "
                f"danmaku={h.danmaku_count}  [{kw_str}]"
            )
            return idx, out_path, msg
        return idx, None, f"  [red][X][/red] Clip {idx + 1} failed."
    finally:
        tmp_path.unlink(missing_ok=True)


def cut_clips_indexed(
    video_path: Path,
    highlights: List[Highlight],
    output_dir: Path,
    title: str = "clip",
    reencode_threshold: float = 2.0,
) -> List[Tuple[int, Path]]:
    """
    Cut a list of Highlight clips from a video.

    Clips are encoded directly with compatibility-friendly codecs.

    Each clip is written to a unique temp file first; only on success is it
    renamed to its final name, so the output directory never contains partial
    files from interrupted or failed encodes.

    Args:
        video_path:          Source video file.
        highlights:          List of Highlight objects from find_highlights().
        output_dir:          Directory to write output clips into.
        title:               Prefix for output filenames.
        reencode_threshold:  Kept for backward compatibility; currently unused.

    Returns:
        List of ``(highlight_index, output_path)`` tuples for successfully
        created clips.
    """
    _ = reencode_threshold

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_title = safe_name(title, max_len=50)
    preset, crf, audio_bitrate = _encode_options()
    workers = _workers(len(highlights))
    console.print(
        f"  [dim]Clip encoding config: preset={preset}, crf={crf}, workers={workers}[/dim]"
    )

    success_by_idx: dict[int, Path] = {}

    if workers <= 1:
        for i, h in enumerate(highlights):
            idx, out_path, msg = _render_one_clip(
                i,
                h,
                video_path,
                output_dir,
                safe_title,
                preset=preset,
                crf=crf,
                audio_bitrate=audio_bitrate,
            )
            console.print(msg)
            if out_path is not None:
                success_by_idx[idx] = out_path
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [
                ex.submit(
                    _render_one_clip,
                    i,
                    h,
                    video_path,
                    output_dir,
                    safe_title,
                    preset=preset,
                    crf=crf,
                    audio_bitrate=audio_bitrate,
                )
                for i, h in enumerate(highlights)
            ]
            for fut in as_completed(futures):
                idx, out_path, msg = fut.result()
                console.print(msg)
                if out_path is not None:
                    success_by_idx[idx] = out_path

    return [(i, success_by_idx[i]) for i in sorted(success_by_idx.keys())]


def cut_clips(
    video_path: Path,
    highlights: List[Highlight],
    output_dir: Path,
    title: str = "clip",
    reencode_threshold: float = 2.0,
) -> List[Path]:
    """Backward-compatible wrapper that returns only successful output paths."""
    return [
        path
        for _, path in cut_clips_indexed(
            video_path,
            highlights,
            output_dir,
            title=title,
            reencode_threshold=reencode_threshold,
        )
    ]
