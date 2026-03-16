"""
Lightweight API routes for local end-to-end usage without Redis/Postgres.

This router is used as a fallback when the full SaaS stack dependencies
(SQLAlchemy/Redis/S3) are unavailable in the current environment.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import shutil
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from stream_clipper.config import PipelineConfig
from stream_clipper.ingest.bili_live import BiliLiveIngest
from stream_clipper.ingest.bili_vod import BiliVodIngest, _normalize_bili_url
from stream_clipper.ingest.local import LocalIngest
from stream_clipper.ingest.web_video import WebLiveIngest, WebVodIngest
from stream_clipper.ml.boundary_adaptation import update_boundary_profile
from stream_clipper.ml.feedback_ranker import (
    default_model_path,
    load_jsonl,
    merge_feedback_with_adjustments,
    save_feedback_model,
    train_feedback_model,
)
from stream_clipper.pipeline import run_pipeline
from stream_clipper.utils import parse_bool, safe_decode

router = APIRouter(prefix="/api/v1")

_JOBS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()
_MAX_CONCURRENT = max(1, int(os.getenv("LITE_MAX_CONCURRENT_JOBS", "1")))
_JOB_SEMAPHORE = threading.BoundedSemaphore(_MAX_CONCURRENT)
_MAX_UPLOAD_MB = max(1, int(os.getenv("LITE_MAX_UPLOAD_MB", "4096")))
_MAX_UPLOAD_BYTES = _MAX_UPLOAD_MB * 1024 * 1024


def _clip_encode_options() -> tuple[str, str, str]:
    preset = os.getenv("CLIP_FFMPEG_PRESET", "ultrafast").strip() or "ultrafast"
    crf = os.getenv("CLIP_FFMPEG_CRF", "23").strip() or "23"
    audio_bitrate = os.getenv("CLIP_FFMPEG_AUDIO_BITRATE", "160k").strip() or "160k"
    return preset, crf, audio_bitrate


def _is_uploaded_file(value: Any) -> bool:
    return bool(
        value is not None
        and hasattr(value, "file")
        and hasattr(value, "filename")
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _output_root() -> Path:
    return Path(os.getenv("OUTPUT_DIR", "./output")) / "_api_jobs"


def _allowed_output_base_dir() -> Optional[Path]:
    raw = os.getenv("LITE_OUTPUT_BASE_DIR", "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    return p.resolve() if p.is_absolute() else (Path.cwd() / p).resolve()


def _native_pick_directory(current: Optional[str] = None) -> Optional[str]:
    """
    Open a native folder picker on the machine running the backend.

    Returns:
      Absolute directory path string, or None if user cancelled.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise RuntimeError("tkinter is unavailable in this Python environment") from exc

    initial = None
    if current:
        try:
            candidate = Path(current).expanduser()
            if not candidate.is_absolute():
                candidate = (Path.cwd() / candidate).resolve()
            if candidate.exists() and candidate.is_dir():
                initial = str(candidate)
        except Exception:
            initial = None

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass

    selected = filedialog.askdirectory(
        parent=root,
        initialdir=initial,
        mustexist=False,
        title="Select output directory",
    )

    try:
        root.destroy()
    except Exception:
        pass

    if not selected:
        return None
    p = Path(selected).expanduser()
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    return str(p)


def _feedback_log_path() -> Path:
    configured = os.getenv("FEEDBACK_LOG_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        return path
    return _output_root() / "_feedback" / "clip_feedback.jsonl"


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _validate_source_url(source_type: str, source_url: Optional[str]) -> Optional[str]:
    if source_url is None:
        return None
    text = str(source_url).strip()
    if not text:
        return None

    if source_type == "bili_live" and text.isdigit():
        return text
    if source_type == "bili_vod" and text.startswith("BV"):
        return text

    from urllib.parse import urlparse

    if source_type in {"web_vod", "web_live"} and "://" not in text and "." in text:
        text = f"https://{text.lstrip('/')}"

    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(400, "source_url 必须使用 http 或 https 协议")
    return text


def _save_upload_with_limit(uploaded_file: UploadFile, dst: Path, max_bytes: int) -> int:
    total = 0
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        with dst.open("wb") as f:
            while True:
                chunk = uploaded_file.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        413,
                        f"上传文件过大（>{_MAX_UPLOAD_MB} MB）。请压缩文件或提高 LITE_MAX_UPLOAD_MB。",
                    )
                f.write(chunk)
    except Exception:
        dst.unlink(missing_ok=True)
        raise
    return total


def _adjustment_log_path() -> Path:
    configured = os.getenv("ADJUSTMENT_LOG_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        return path
    return _output_root() / "_feedback" / "clip_adjustments.jsonl"


def _safe_job_video_path(job: Dict[str, Any]) -> Optional[Path]:
    job_dir = Path(job["job_dir"]).resolve()
    source_type = str(job.get("source_type", ""))

    if source_type == "local":
        p = job.get("input_video_path")
        if p:
            candidate = Path(str(p)).resolve()
            if candidate.exists() and candidate.is_file():
                return candidate
        local_dir = job_dir / "input"
        videos = sorted(local_dir.glob("*.mp4"), key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)
        if videos:
            return videos[0].resolve()
        return None

    if source_type in {"bili_vod", "web_vod"}:
        ingest_dir = job_dir / "_ingest"
        videos = sorted(ingest_dir.glob("*.mp4"), key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)
        if videos:
            return videos[0].resolve()
        return None

    if source_type in {"bili_live", "web_live"}:
        rec_dir = job_dir / "_recording"
        videos = sorted(rec_dir.glob("*.mp4"), key=lambda x: x.stat().st_mtime if x.exists() else 0, reverse=True)
        if videos:
            return videos[0].resolve()
        return None

    return None


def _run_ffmpeg(cmd: list[str], timeout_sec: int = 900) -> tuple[int, str]:
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout_sec)
    except FileNotFoundError as exc:
        raise RuntimeError("未在 PATH 中找到 ffmpeg") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("ffmpeg timeout while recutting clip") from exc
    return result.returncode, safe_decode(result.stderr, preferred_encoding="utf-8")


def _cut_clip_h264(
    source_video: Path,
    out_path: Path,
    clip_start: float,
    clip_end: float,
    *,
    fast_preview: bool = False,
) -> str:
    duration = max(0.1, float(clip_end) - float(clip_start))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    preset, crf, audio_bitrate = _clip_encode_options()
    if fast_preview:
        fast_cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(float(clip_start)),
            "-i",
            str(source_video),
            "-t",
            str(duration),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            "-avoid_negative_ts",
            "make_zero",
            str(out_path),
        ]
        rc, stderr = _run_ffmpeg(fast_cmd, timeout_sec=120)
        if rc == 0 and out_path.exists() and out_path.stat().st_size > 1024:
            return "copy"

    encode_cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(float(clip_start)),
        "-i",
        str(source_video),
        "-t",
        str(duration),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        crf,
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    rc, stderr = _run_ffmpeg(encode_cmd, timeout_sec=900)
    if rc != 0:
        raise RuntimeError(f"ffmpeg 重新裁剪失败：{stderr[-1200:]}")
    return "reencode"


def _resolve_output_dir(job_id: str, requested: Optional[str]) -> Path:
    """
    Resolve per-job output directory.

    If requested is provided, treat it as a base folder chosen by user and
    write artifacts into <requested>/<job_id>. Otherwise use default API path.
    """
    if requested and str(requested).strip():
        base = Path(str(requested).strip()).expanduser()
        if not base.is_absolute():
            base = (Path.cwd() / base).resolve()
        else:
            base = base.resolve()
        allowed_base = _allowed_output_base_dir()
        if allowed_base and not _is_relative_to(base, allowed_base):
            raise OSError(
                f"output_dir must be under {allowed_base} "
                "(configure via LITE_OUTPUT_BASE_DIR)."
            )
        return base / job_id
    return _output_root() / job_id / "output"


def _new_job(
    source_type: str,
    source_url: Optional[str],
    options: Dict[str, Any],
) -> Dict[str, Any]:
    job_id = str(uuid.uuid4())
    job_dir = _output_root() / job_id
    output_dir = _resolve_output_dir(job_id, options.get("output_dir"))
    job_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    return {
        "job_id": job_id,
        "status": "queued",
        "progress": 0.0,
        "current_stage": None,
        "error": None,
        "source_type": source_type,
        "source_url": source_url,
        "options": options,
        "created_at": _utc_now(),
        "started_at": None,
        "completed_at": None,
        "position": None,
        "job_dir": str(job_dir),
        "output_dir": str(output_dir),
        "input_video_path": None,
        "video_duration": 0.0,
        "clips": [],
        "events": [],
    }


def _refresh_positions() -> None:
    """Refresh queue position for jobs still waiting to be processed."""
    queued = sorted(
        (j for j in _JOBS.values() if j.get("status") == "queued"),
        key=lambda x: x.get("created_at") or _utc_now(),
    )
    for idx, j in enumerate(queued, start=1):
        j["position"] = idx
    for j in _JOBS.values():
        if j.get("status") != "queued":
            j["position"] = None


def _publish(job: Dict[str, Any], stage: str, progress: float) -> None:
    job["current_stage"] = stage
    job["progress"] = max(0.0, min(1.0, float(progress)))
    job["events"].append(
        {
            "stage": stage,
            "progress": round(job["progress"], 3),
            "timestamp": _utc_now().isoformat(),
        }
    )


def _job_response(job: Dict[str, Any]) -> Dict[str, Any]:
    clips = [dict(c) for c in job.get("clips", [])]
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "progress": job["progress"],
        "current_stage": job["current_stage"],
        "position": job.get("position"),
        "clips": clips,
        "error": job["error"],
        "output_dir": job.get("output_dir"),
        "created_at": job["created_at"],
        "started_at": job["started_at"],
        "completed_at": job["completed_at"],
    }


def _build_config(options: Dict[str, Any]) -> PipelineConfig:
    top_n = max(1, min(50, int(options.get("top_n", 10))))
    model_size = str(options.get("model_size", os.getenv("WHISPER_MODEL", "tiny")))
    language = options.get("language", "zh")
    clip_duration = float(options.get("clip_duration", 45.0))
    clip_duration = max(5.0, min(3600.0, clip_duration))
    # Keep previous asymmetric context ratio: 1/3 before, 2/3 after peak.
    pad_before = clip_duration / 3.0
    pad_after = clip_duration - pad_before
    if language == "auto":
        language = None
    feedback_rank = parse_bool(options.get("feedback_rank", True), True)
    feedback_model_path = str(options.get("feedback_model_path", "")).strip() or None
    llm_rerank = parse_bool(
        options.get("llm_rerank"),
        parse_bool(os.getenv("ENABLE_LLM_RERANK", "0"), False),
    )
    llm_model = str(options.get("llm_model", "")).strip() or None
    llm_max_candidates = max(1, int(options.get("llm_max_candidates", 20)))
    llm_score_weight = float(options.get("llm_score_weight", 0.65))
    llm_timeout_sec = float(options.get("llm_timeout_sec", 30.0))
    semantic_enrichment = parse_bool(
        options.get("semantic_enrichment"),
        parse_bool(os.getenv("ENABLE_SEMANTIC_ENRICHMENT", "0"), False),
    )
    semantic_model = str(options.get("semantic_model", "")).strip() or None
    semantic_max_candidates = max(1, int(options.get("semantic_max_candidates", 8)))
    semantic_score_weight = float(options.get("semantic_score_weight", 0.2))
    semantic_timeout_sec = float(options.get("semantic_timeout_sec", 30.0))
    boundary_adaptation = parse_bool(options.get("boundary_adaptation", True), True)
    boundary_profile_path = str(options.get("boundary_profile_path", "")).strip() or None
    return PipelineConfig(
        model_size=model_size,
        language=language,
        top_n=top_n,
        candidate_multiplier=max(1, int(options.get("candidate_multiplier", 3))),
        pad_before=pad_before,
        pad_after=pad_after,
        threshold=options.get("threshold"),
        adaptive_padding=parse_bool(options.get("adaptive_padding", True), True),
        half_peak_ratio=float(options.get("half_peak_ratio", 0.5)),
        adaptive_min_before=float(options.get("adaptive_min_before", 5.0)),
        adaptive_max_before=float(options.get("adaptive_max_before", 45.0)),
        adaptive_min_after=float(options.get("adaptive_min_after", 8.0)),
        adaptive_max_after=float(options.get("adaptive_max_after", 60.0)),
        enable_feedback_ranking=feedback_rank,
        feedback_model_path=feedback_model_path,
        enable_llm_rerank=llm_rerank,
        llm_model=llm_model,
        llm_max_candidates=llm_max_candidates,
        llm_score_weight=llm_score_weight,
        llm_timeout_sec=llm_timeout_sec,
        enable_semantic_enrichment=semantic_enrichment,
        semantic_model=semantic_model,
        semantic_max_candidates=semantic_max_candidates,
        semantic_score_weight=semantic_score_weight,
        semantic_timeout_sec=semantic_timeout_sec,
        enable_boundary_adaptation=boundary_adaptation,
        boundary_profile_path=boundary_profile_path,
    )


def _path_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def _cleanup_source_artifacts(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    Delete downloaded/intermediate source artifacts for a job.

    Keeps exported clips and output artifacts intact.
    """
    job_dir = Path(job["job_dir"]).resolve()
    source_type = job.get("source_type")
    candidates = []

    if source_type in {"bili_vod", "bili_live", "web_vod", "web_live"}:
        candidates.extend(
            [
                job_dir / "_ingest",
                job_dir / "_recording",
                job_dir / "input",
            ]
        )
    elif source_type == "local":
        # Optional cleanup for uploaded local copies.
        candidates.append(job_dir / "input")

    removed = []
    freed_bytes = 0
    for target in candidates:
        t = target.resolve()
        if not t.exists():
            continue
        if job_dir not in t.parents and t != job_dir:
            continue
        freed_bytes += _path_size_bytes(t)
        try:
            if t.is_dir():
                shutil.rmtree(t, ignore_errors=False)
            else:
                t.unlink(missing_ok=True)
            removed.append(str(t))
        except Exception:
            pass

    return {
        "removed_paths": removed,
        "freed_bytes": int(freed_bytes),
        "freed_mb": round(freed_bytes / (1024 * 1024), 2),
    }


def _cleanup_unselected_clips(
    job: Dict[str, Any],
    keep_clip_ids: set[str],
) -> Dict[str, Any]:
    """
    Keep only selected clips and remove unselected clip files from output_dir.
    """
    output_dir = Path(str(job.get("output_dir", ""))).resolve()
    clips = list(job.get("clips", []))

    kept_clips: list[Dict[str, Any]] = []
    removed_clip_ids: list[str] = []
    removed_paths: list[str] = []
    freed_bytes = 0

    for clip in clips:
        clip_id = str(clip.get("id", "") or "").strip()
        if clip_id and clip_id in keep_clip_ids:
            kept_clips.append(clip)
            continue

        removed_clip_ids.append(clip_id or "(unknown)")
        file_name = str(
            clip.get("file_name")
            or clip.get("file")
            or ""
        ).strip()
        if not file_name:
            continue

        clip_path = (output_dir / file_name).resolve()
        if output_dir not in clip_path.parents:
            continue
        if not clip_path.exists() or not clip_path.is_file():
            continue

        try:
            freed_bytes += clip_path.stat().st_size
        except OSError:
            pass

        try:
            clip_path.unlink(missing_ok=True)
            removed_paths.append(str(clip_path))
        except Exception:
            pass

    job["clips"] = kept_clips
    return {
        "kept_count": len(kept_clips),
        "removed_count": len(removed_clip_ids),
        "removed_clip_ids": removed_clip_ids,
        "removed_paths": removed_paths,
        "freed_bytes": int(freed_bytes),
        "freed_mb": round(freed_bytes / (1024 * 1024), 2),
    }


def _run_job(job_id: str) -> None:
    # Wait for slot instead of failing queued jobs under burst traffic.
    _JOB_SEMAPHORE.acquire()

    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            _JOB_SEMAPHORE.release()
            return
        job["status"] = "processing"
        job["started_at"] = _utc_now()
        _publish(job, "download", 0.08)
        _refresh_positions()
        source_type = job["source_type"]
        source_url = job["source_url"]
        options = dict(job["options"])
        input_video_path = job.get("input_video_path")
        job_dir = Path(job["job_dir"])
        output_dir = Path(job["output_dir"])

    try:
        if source_type == "local":
            if not input_video_path:
                raise ValueError("本地任务缺少上传文件")
            ingest = LocalIngest(video_path=input_video_path, danmaku_path=None)
        elif source_type == "bili_vod":
            if not source_url:
                raise ValueError("哔哩哔哩任务必须提供视频链接")
            with _LOCK:
                _publish(job, "danmaku", 0.18)

            def _vod_progress_cb(progress: float) -> None:
                with _LOCK:
                    if job.get("status") == "processing":
                        _publish(job, "danmaku", progress)

            ingest = BiliVodIngest(
                url=source_url,
                work_dir=str(job_dir / "_ingest"),
                cookies_file=options.get("cookies_file"),
                sessdata=os.getenv("BILI_SESSDATA"),
                proxy=options.get("proxy") or os.getenv("HTTPS_PROXY"),
                progress_cb=_vod_progress_cb,
            )
        elif source_type == "bili_live":
            if not source_url:
                raise ValueError("直播任务必须提供链接")
            with _LOCK:
                _publish(job, "danmaku", 0.18)
            max_seconds = int(options.get("duration", 180))

            def _live_progress_cb(elapsed: float, n_comments: int) -> None:
                _ = n_comments
                # Map live recording progress into danmaku->asr span: [0.18, 0.42].
                if max_seconds <= 0:
                    return
                ratio = max(0.0, min(1.0, float(elapsed) / float(max_seconds)))
                p = 0.18 + 0.24 * ratio
                with _LOCK:
                    if job.get("status") == "processing":
                        _publish(job, "danmaku", p)

            ingest = BiliLiveIngest(
                url=source_url,
                work_dir=str(job_dir / "_recording"),
                max_seconds=max_seconds,
                progress_cb=_live_progress_cb,
            )
        elif source_type == "web_vod":
            if not source_url:
                raise ValueError("网页视频任务必须提供来源链接")
            with _LOCK:
                _publish(job, "danmaku", 0.18)

            def _web_vod_progress_cb(progress: float) -> None:
                with _LOCK:
                    if job.get("status") == "processing":
                        _publish(job, "danmaku", progress)

            ingest = WebVodIngest(
                url=source_url,
                work_dir=str(job_dir / "_ingest"),
                proxy=options.get("proxy") or os.getenv("HTTPS_PROXY"),
                progress_cb=_web_vod_progress_cb,
            )
        elif source_type == "web_live":
            if not source_url:
                raise ValueError("网页直播任务必须提供链接")
            with _LOCK:
                _publish(job, "danmaku", 0.18)
            max_seconds = int(options.get("duration", 180))

            def _web_live_progress_cb(elapsed: float, n_comments: int) -> None:
                _ = n_comments
                if max_seconds <= 0:
                    return
                ratio = max(0.0, min(1.0, float(elapsed) / float(max_seconds)))
                p = 0.18 + 0.24 * ratio
                with _LOCK:
                    if job.get("status") == "processing":
                        _publish(job, "danmaku", p)

            ingest = WebLiveIngest(
                url=source_url,
                work_dir=str(job_dir / "_recording"),
                max_seconds=max_seconds,
                proxy=options.get("proxy") or os.getenv("HTTPS_PROXY"),
                progress_cb=_web_live_progress_cb,
            )
        else:
            raise ValueError(f"不支持的 source_type：{source_type}")

        ingest_result = ingest.run()
        with _LOCK:
            job["video_duration"] = float(getattr(ingest_result, "duration", 0.0) or 0.0)

        with _LOCK:
            _publish(job, "asr", 0.42)

        cfg = _build_config(options)
        clip_paths = run_pipeline(
            ingest_result=ingest_result,
            output_dir=str(output_dir),
            config=cfg,
        )

        with _LOCK:
            _publish(job, "scoring", 0.72)
            _publish(job, "clipping", 0.86)
            _publish(job, "upload", 0.95)

        summary_path = output_dir / "summary.json"
        summary = {}
        if summary_path.exists():
            summary = json.loads(safe_decode(summary_path.read_bytes(), preferred_encoding="utf-8"))

        highlights = summary.get("highlights", [])
        ranking_source = summary.get("ranking_source", "resonance")
        boundary_adaptation = summary.get("boundary_adaptation", {"enabled": False})
        clips = []
        for i, h in enumerate(highlights):
            fname = h.get("file")
            if not fname:
                continue
            clips.append(
                {
                    "id": f"{job_id}-{i + 1}",
                    "job_id": job_id,
                    "clip_start": h.get("clip_start", 0.0),
                    "clip_end": h.get("clip_end", 0.0),
                    "duration": float(h.get("clip_end", 0.0)) - float(h.get("clip_start", 0.0)),
                    "highlight_score": h.get("score"),
                    "score": h.get("score"),
                    "rank_score": h.get("rank_score", h.get("score")),
                    "llm_score": h.get("llm_score"),
                    "llm_title": h.get("llm_title"),
                    "llm_reason": h.get("llm_reason"),
                    "ranking_source": ranking_source,
                    "boundary_adaptation": boundary_adaptation,
                    "virality_score": None,
                    "transcript": h.get("content_summary"),
                    "content_summary": h.get("content_summary"),
                    "content_tags": h.get("content_tags", []),
                    "semantic_score": h.get("semantic_score"),
                    "content_hook": h.get("content_hook", False),
                    "danmaku_count": h.get("danmaku_count", 0),
                    "top_keywords": h.get("top_keywords", []),
                    "ai_clip_start": h.get("ai_clip_start", h.get("clip_start", 0.0)),
                    "ai_clip_end": h.get("ai_clip_end", h.get("clip_end", 0.0)),
                    "file_name": fname,
                    "index": i,
                    "adjustments": 0,
                    "download_url": f"/api/v1/files/{job_id}/{fname}",
                    "thumbnail_url": None,
                    "created_at": _utc_now(),
                }
            )

        with _LOCK:
            job["clips"] = clips
            job["status"] = "completed"
            job["completed_at"] = _utc_now()
            _publish(job, "completed", 1.0)
            _refresh_positions()

        # Keep local artifacts for user downloads.
        _ = clip_paths

    except Exception as exc:
        with _LOCK:
            job["status"] = "failed"
            job["error"] = str(exc)
            job["completed_at"] = _utc_now()
            _publish(job, "failed", job.get("progress", 0.0))
            _refresh_positions()
    finally:
        _JOB_SEMAPHORE.release()


@router.post("/jobs")
async def create_job(request: Request):
    ctype = request.headers.get("content-type", "")
    source_type = ""
    source_url: Optional[str] = None
    options: Dict[str, Any] = {}
    uploaded_file: Optional[UploadFile] = None

    if "multipart/form-data" in ctype:
        form = await request.form()
        source_type = str(form.get("source_type", "")).strip()
        source_url_raw = form.get("source_url")
        source_url = str(source_url_raw).strip() if source_url_raw else None
        try:
            options["top_n"] = int(form.get("top_n", 10))
            options["clip_duration"] = float(form.get("clip_duration", 45))
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "Invalid top_n or clip_duration") from exc
        options["model_size"] = str(form.get("model_size", "base"))
        options["language"] = str(form.get("language", "zh"))
        options["output_dir"] = str(form.get("output_dir", "")).strip()
        try:
            options["candidate_multiplier"] = int(form.get("candidate_multiplier", 3))
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "Invalid candidate_multiplier") from exc
        options["feedback_rank"] = str(form.get("feedback_rank", "true")).strip()
        options["feedback_model_path"] = str(form.get("feedback_model_path", "")).strip()
        if form.get("llm_rerank") is not None:
            options["llm_rerank"] = str(form.get("llm_rerank")).strip()
        options["llm_model"] = str(form.get("llm_model", "")).strip()
        options["llm_max_candidates"] = form.get("llm_max_candidates", 20)
        options["llm_score_weight"] = form.get("llm_score_weight", 0.65)
        options["llm_timeout_sec"] = form.get("llm_timeout_sec", 30.0)
        options["boundary_adaptation"] = str(form.get("boundary_adaptation", "true")).strip()
        options["boundary_profile_path"] = str(form.get("boundary_profile_path", "")).strip()
        options["adaptive_padding"] = str(form.get("adaptive_padding", "true")).strip()
        options["half_peak_ratio"] = form.get("half_peak_ratio", 0.5)
        options["adaptive_min_before"] = form.get("adaptive_min_before", 5.0)
        options["adaptive_max_before"] = form.get("adaptive_max_before", 45.0)
        options["adaptive_min_after"] = form.get("adaptive_min_after", 8.0)
        options["adaptive_max_after"] = form.get("adaptive_max_after", 60.0)
        uploaded_file = form.get("file")  # type: ignore[assignment]
    else:
        try:
            payload = await request.json()
        except Exception as exc:
            raise HTTPException(400, "Invalid request payload") from exc
        source_type = str(payload.get("source_type", "")).strip()
        source_url = payload.get("source_url")
        try:
            options["top_n"] = int(payload.get("top_n", 10))
            options["clip_duration"] = float(payload.get("clip_duration", 45))
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "Invalid top_n or clip_duration") from exc
        options["model_size"] = str(payload.get("model_size", "base"))
        options["language"] = payload.get("language", "zh")
        options["duration"] = int(payload.get("duration", 1800))
        options["output_dir"] = str(payload.get("output_dir", "")).strip()
        try:
            options["candidate_multiplier"] = int(payload.get("candidate_multiplier", 3))
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "Invalid candidate_multiplier") from exc
        options["feedback_rank"] = payload.get("feedback_rank", True)
        options["feedback_model_path"] = str(payload.get("feedback_model_path", "")).strip()
        if "llm_rerank" in payload:
            options["llm_rerank"] = payload.get("llm_rerank")
        options["llm_model"] = str(payload.get("llm_model", "")).strip()
        options["llm_max_candidates"] = payload.get("llm_max_candidates", 20)
        options["llm_score_weight"] = payload.get("llm_score_weight", 0.65)
        options["llm_timeout_sec"] = payload.get("llm_timeout_sec", 30.0)
        options["boundary_adaptation"] = payload.get("boundary_adaptation", True)
        options["boundary_profile_path"] = str(payload.get("boundary_profile_path", "")).strip()
        options["adaptive_padding"] = payload.get("adaptive_padding", True)
        options["half_peak_ratio"] = payload.get("half_peak_ratio", 0.5)
        options["adaptive_min_before"] = payload.get("adaptive_min_before", 5.0)
        options["adaptive_max_before"] = payload.get("adaptive_max_before", 45.0)
        options["adaptive_min_after"] = payload.get("adaptive_min_after", 8.0)
        options["adaptive_max_after"] = payload.get("adaptive_max_after", 60.0)

    if source_type not in {"local", "bili_vod", "bili_live", "web_vod", "web_live"}:
        raise HTTPException(400, "source_type 必须是以下之一：local、bili_vod、bili_live、web_vod、web_live")
    if source_type in {"bili_vod", "bili_live", "web_vod", "web_live"} and not source_url:
        raise HTTPException(400, "外部视频/直播任务必须提供 source_url")

    if source_type == "bili_vod" and source_url:
        source_url = _normalize_bili_url(source_url)
    source_url = _validate_source_url(source_type, source_url)

    try:
        job = _new_job(source_type=source_type, source_url=source_url, options=options)
    except OSError as exc:
        raise HTTPException(400, f"output_dir 无效：{exc}") from exc

    if source_type == "local":
        if not _is_uploaded_file(uploaded_file):
            raise HTTPException(400, "本地来源必须上传视频文件")

        input_dir = Path(job["job_dir"]) / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(uploaded_file.filename or "source.mp4").suffix or ".mp4"
        input_path = input_dir / f"source{suffix}"
        _save_upload_with_limit(uploaded_file, input_path, _MAX_UPLOAD_BYTES)
        job["input_video_path"] = str(input_path)

    with _LOCK:
        _JOBS[job["job_id"]] = job
        _refresh_positions()

    threading.Thread(target=_run_job, args=(job["job_id"],), daemon=True).start()

    return _job_response(job)


@router.get("/jobs")
async def list_jobs():
    with _LOCK:
        jobs = [_job_response(j) for j in _JOBS.values()]
    jobs.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return {
        "jobs": jobs,
        "total": len(jobs),
        "page": 1,
        "pages": 1,
    }


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        return _job_response(job)


@router.post("/jobs/{job_id}/cleanup-source")
async def cleanup_job_source(job_id: str):
    """
    Cleanup downloaded source artifacts for a completed/failed job.

    Safe to call multiple times.
    """
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if job.get("status") in {"queued", "processing"}:
            raise HTTPException(409, "任务仍在运行中")
        job_copy = copy.deepcopy(job)

    result = _cleanup_source_artifacts(job_copy)
    return {
        "status": "ok",
        "job_id": job_id,
        **result,
    }


@router.post("/jobs/{job_id}/cleanup-unselected-clips")
async def cleanup_unselected_clips(job_id: str, request: Request):
    """
    Delete clip files that are not selected and keep only selected clips.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    keep_ids = payload.get("keep_clip_ids") or payload.get("selected_clip_ids") or []
    if not isinstance(keep_ids, list):
        raise HTTPException(400, "keep_clip_ids must be a list")

    keep_set = {str(x).strip() for x in keep_ids if str(x).strip()}
    if not keep_set:
        raise HTTPException(400, "keep_clip_ids cannot be empty")

    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "job not found")
        if job.get("status") in {"queued", "processing"}:
            raise HTTPException(409, "job is still running")
        result = _cleanup_unselected_clips(job, keep_set)

    return {
        "status": "ok",
        "job_id": job_id,
        **result,
    }


@router.get("/jobs/{job_id}/stream")
async def stream_job_progress(job_id: str, request: Request):
    with _LOCK:
        job = _JOBS.get(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")

    async def event_stream():
        index = 0
        while True:
            if await request.is_disconnected():
                break

            with _LOCK:
                job_obj = _JOBS.get(job_id)
                if not job_obj:
                    break
                events = job_obj["events"][index:]
                status = job_obj["status"]

            for evt in events:
                index += 1
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"

            if status in {"completed", "failed"} and not events:
                break
            await asyncio.sleep(0.4)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/clips")
async def list_clips():
    clips = []
    with _LOCK:
        for job in _JOBS.values():
            clips.extend(job.get("clips", []))
    clips.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
    return {
        "clips": clips,
        "total": len(clips),
        "page": 1,
        "pages": 1,
    }


@router.get("/clips/{clip_id}")
async def get_clip(clip_id: str):
    with _LOCK:
        for job in _JOBS.values():
            for clip in job.get("clips", []):
                if clip.get("id") == clip_id:
                    return clip
    raise HTTPException(404, "片段不存在")


@router.post("/clips/{clip_id}/adjust")
async def adjust_clip_bounds(clip_id: str, request: Request):
    """
    Re-cut one clip with user-adjusted boundaries and persist learning signal.
    """
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(400, "Invalid request payload") from exc

    try:
        new_start = float(payload.get("clip_start"))
        new_end = float(payload.get("clip_end"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "clip_start 和 clip_end 必须是数字") from exc

    note = str(payload.get("note", "")).strip()
    fast_preview = parse_bool(payload.get("fast_preview", False), False)
    if len(note) > 500:
        raise HTTPException(400, "note 长度不能超过 500 个字符")

    with _LOCK:
        clip_obj: Optional[Dict[str, Any]] = None
        job_obj: Optional[Dict[str, Any]] = None
        for j in _JOBS.values():
            for c in j.get("clips", []):
                if c.get("id") == clip_id:
                    clip_obj = c
                    job_obj = j
                    break
            if clip_obj is not None:
                break

    if clip_obj is None or job_obj is None:
        raise HTTPException(404, "片段不存在")

    if job_obj.get("status") != "completed":
        raise HTTPException(409, "任务尚未完成，暂不可调整片段")

    job_duration = float(job_obj.get("video_duration") or 0.0)
    if job_duration <= 0:
        # fallback from clips
        job_duration = max(
            float(clip_obj.get("clip_end", 0.0)),
            float(clip_obj.get("ai_clip_end", 0.0)),
            1.0,
        )

    if new_start < 0 or new_end <= new_start:
        raise HTTPException(400, "片段边界无效")
    if new_end > job_duration + 1e-6:
        raise HTTPException(400, "clip_end 超出视频总时长")
    if new_end - new_start < 2.0:
        raise HTTPException(400, "片段时长必须大于等于 2 秒")

    source_video = _safe_job_video_path(job_obj)
    if not source_video or not source_video.exists():
        raise HTTPException(409, "源视频不可用。若需后续可编辑，请关闭源文件自动清理。")

    output_dir = Path(job_obj["output_dir"]).resolve()
    file_name = str(clip_obj.get("file_name") or "")
    if not file_name:
        idx = int(clip_obj.get("index", 0))
        file_name = f"clip_{idx + 1:02d}.mp4"
        clip_obj["file_name"] = file_name

    target_path = (output_dir / file_name).resolve()
    if output_dir not in target_path.parents:
        raise HTTPException(403, "输出路径不允许访问")

    try:
        cut_mode = _cut_clip_h264(
            source_video,
            target_path,
            new_start,
            new_end,
            fast_preview=fast_preview,
        )
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc

    with _LOCK:
        prev_start = float(clip_obj.get("clip_start", 0.0))
        prev_end = float(clip_obj.get("clip_end", 0.0))

        clip_obj["clip_start"] = new_start
        clip_obj["clip_end"] = new_end
        clip_obj["duration"] = new_end - new_start
        clip_obj["download_url"] = f"/api/v1/files/{clip_obj.get('job_id')}/{file_name}?v={int(_utc_now().timestamp() * 1000)}"
        clip_obj["adjustments"] = int(clip_obj.get("adjustments", 0)) + 1
        clip_obj["last_adjusted_at"] = _utc_now().isoformat()

        ai_start = float(clip_obj.get("ai_clip_start", prev_start))
        ai_end = float(clip_obj.get("ai_clip_end", prev_end))
        delta_start = new_start - ai_start
        delta_end = new_end - ai_end
        profile = update_boundary_profile(delta_start, delta_end)

        adj_record = {
            "clip_id": clip_obj.get("id"),
            "job_id": clip_obj.get("job_id"),
            "source_type": job_obj.get("source_type"),
            "source_url": job_obj.get("source_url"),
            "ai_clip_start": ai_start,
            "ai_clip_end": ai_end,
            "prev_clip_start": prev_start,
            "prev_clip_end": prev_end,
            "new_clip_start": new_start,
            "new_clip_end": new_end,
            "delta_start_vs_ai": delta_start,
            "delta_end_vs_ai": delta_end,
            "note": note or None,
            "feedback": clip_obj.get("feedback"),
            "adjusted_at": clip_obj["last_adjusted_at"],
        }

        log_path = _adjustment_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(adj_record, ensure_ascii=False) + "\n")

    return {
        "status": "ok",
        "clip": clip_obj,
        "cut_mode": cut_mode,
        "boundary_profile": {
            "count": profile.get("count", 0),
            "mean_start_delta": profile.get("mean_start_delta", 0.0),
            "mean_end_delta": profile.get("mean_end_delta", 0.0),
        },
    }


@router.delete("/clips/{clip_id}", status_code=204)
async def delete_clip(clip_id: str):
    with _LOCK:
        for job in _JOBS.values():
            clips = job.get("clips", [])
            for i, clip in enumerate(clips):
                if clip.get("id") == clip_id:
                    clips.pop(i)
                    return JSONResponse(status_code=204, content={})
    raise HTTPException(404, "片段不存在")


@router.post("/clips/{clip_id}/feedback")
async def submit_clip_feedback(clip_id: str, request: Request):
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(400, "Invalid request payload") from exc

    rating = str(payload.get("rating", "")).strip().lower()
    if rating not in {"good", "average", "bad"}:
        raise HTTPException(400, "rating must be one of: good, average, bad")
    note = str(payload.get("note", "")).strip()
    if len(note) > 500:
        raise HTTPException(400, "note 长度不能超过 500 个字符")

    clip_obj: Optional[Dict[str, Any]] = None
    job_obj: Optional[Dict[str, Any]] = None
    with _LOCK:
        for j in _JOBS.values():
            for c in j.get("clips", []):
                if c.get("id") == clip_id:
                    clip_obj = c
                    job_obj = j
                    break
            if clip_obj is not None:
                break

        if clip_obj is None or job_obj is None:
            raise HTTPException(404, "片段不存在")

        clip_obj["feedback"] = rating
        clip_obj["feedback_note"] = note or None
        clip_obj["feedback_at"] = _utc_now().isoformat()

        record = {
            "clip_id": clip_obj.get("id"),
            "job_id": clip_obj.get("job_id"),
            "rating": rating,
            "note": note or None,
            "feedback_at": clip_obj["feedback_at"],
            "source_type": job_obj.get("source_type"),
            "source_url": job_obj.get("source_url"),
            "job_options": job_obj.get("options", {}),
            "clip_start": clip_obj.get("clip_start"),
            "clip_end": clip_obj.get("clip_end"),
            "duration": clip_obj.get("duration"),
            "score": clip_obj.get("score"),
            "danmaku_count": clip_obj.get("danmaku_count"),
            "top_keywords": clip_obj.get("top_keywords", []),
            "adjustments": int(clip_obj.get("adjustments", 0) or 0),
            "ai_clip_start": clip_obj.get("ai_clip_start"),
            "ai_clip_end": clip_obj.get("ai_clip_end"),
            "delta_start_vs_ai": (
                float(clip_obj.get("clip_start", 0.0))
                - float(clip_obj.get("ai_clip_start", clip_obj.get("clip_start", 0.0)))
            ),
            "delta_end_vs_ai": (
                float(clip_obj.get("clip_end", 0.0))
                - float(clip_obj.get("ai_clip_end", clip_obj.get("clip_end", 0.0)))
            ),
        }

        log_path = _feedback_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return {"status": "ok", "clip_id": clip_id, "rating": rating}


@router.post("/feedback/retrain")
async def retrain_feedback_ranker(request: Request):
    """
    Retrain feedback ranking model from JSONL logs.

    Request body (all optional):
      - input_path: path to feedback jsonl
      - output_path: model output json path
      - adjustment_input_path: path to adjustment jsonl (default: ADJUSTMENT_LOG_PATH)
      - min_samples: minimum rows to train
      - l2_alpha: ridge regularization coefficient
    """
    payload: Dict[str, Any] = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    input_path_raw = str(payload.get("input_path", "")).strip()
    output_path_raw = str(payload.get("output_path", "")).strip()
    adjustment_input_path_raw = str(payload.get("adjustment_input_path", "")).strip()
    try:
        min_samples = int(payload.get("min_samples", 8))
        l2_alpha = float(payload.get("l2_alpha", 0.2))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Invalid min_samples or l2_alpha") from exc

    input_path = Path(input_path_raw).expanduser() if input_path_raw else _feedback_log_path()
    if not input_path.is_absolute():
        input_path = (Path.cwd() / input_path).resolve()
    output_path = Path(output_path_raw).expanduser() if output_path_raw else default_model_path()
    if not output_path.is_absolute():
        output_path = (Path.cwd() / output_path).resolve()
    adjustment_input_path = (
        Path(adjustment_input_path_raw).expanduser()
        if adjustment_input_path_raw
        else _adjustment_log_path()
    )
    if not adjustment_input_path.is_absolute():
        adjustment_input_path = (Path.cwd() / adjustment_input_path).resolve()

    rows = load_jsonl(input_path)
    adjustment_rows = load_jsonl(adjustment_input_path)
    merged_rows = merge_feedback_with_adjustments(rows, adjustment_rows)
    try:
        model = train_feedback_model(
            merged_rows,
            min_samples=max(1, min_samples),
            l2_alpha=max(0.0, l2_alpha),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    saved = save_feedback_model(model, output_path)
    return {
        "status": "ok",
        "input_path": str(input_path),
        "adjustment_input_path": str(adjustment_input_path),
        "output_path": str(saved),
        "n_samples": model.get("n_samples", 0),
        "merged_rows": len(merged_rows),
        "metrics": model.get("metrics", {}),
        "feature_keys": model.get("feature_keys", []),
    }


@router.post("/upload/presign")
async def upload_presign():
    raise HTTPException(
        status_code=501,
        detail="Presigned uploads are disabled in lite mode. Use local job upload instead.",
    )


@router.get("/system/select-output-dir")
async def select_output_dir(current: Optional[str] = None):
    """
    Open OS-native folder picker and return selected absolute path.

    Notes:
      - Only meaningful in local desktop usage (API + browser on same machine).
      - Returns {"selected": null} when user cancels.
    """
    if not parse_bool(os.getenv("ENABLE_NATIVE_DIR_PICKER", "1"), True):
        raise HTTPException(403, "Native directory picker is disabled by server config")

    try:
        selected = _native_pick_directory(current=current)
    except Exception as exc:
        raise HTTPException(501, f"Native folder picker unavailable: {exc}") from exc

    return {"selected": selected}


@router.get("/files/{job_id}/{filename:path}")
async def serve_clip_file(job_id: str, filename: str):
    with _LOCK:
        job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")

    job_output = Path(job["output_dir"]).resolve()
    target = (job_output / filename).resolve()
    if job_output not in target.parents:
        raise HTTPException(403, "Forbidden path")
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(target)
