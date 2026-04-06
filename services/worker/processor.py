"""
CPU worker that orchestrates the full clipping pipeline.

Each job goes through 6 stages with checkpointing:
  1. DOWNLOAD  — fetch video (VOD/live/S3) + upload raw to S3
  2. DANMAKU   — fetch/parse danmaku comments
  3. ASR       — call GPU inference service for transcription
  4. SCORING   — resonance scoring + peak detection
  5. CLIPPING  — FFmpeg clip cutting
  6. UPLOAD    — upload clips + thumbnails to S3, create DB records

On failure, the worker retries from the last successful checkpoint.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from services.db.models import Job, JobStatus
from services.db.queries import (
    create_clip_sync,
    get_job_sync,
    record_usage_sync,
)
from services.db.session import get_sync_db
from services.queue.job_queue import JobQueue
from services.storage.s3 import S3Storage
from stream_clipper.clipper.ffmpeg_clipper import cut_clips_indexed
from stream_clipper.config import resolve_clip_window
from stream_clipper.ml.feedback_ranker import (
    default_model_path,
    extract_features,
    load_feedback_model,
    predict_quality,
)
from stream_clipper.ml.boundary_adaptation import apply_boundary_adaptation, load_boundary_profile
from stream_clipper.ml.llm_reranker import LLMRerankConfig, analyze_candidates_with_llm
from stream_clipper.audio_features import compute_rms_energy_per_second
from stream_clipper.ingest.ytdlp_guard import ensure_ytdlp_ready
from stream_clipper.resonance.peaks import Highlight
from stream_clipper.utils import parse_bool, safe_decode

from .inference_client import InferenceClient

logger = logging.getLogger(__name__)


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return float(value)


class StageError(Exception):
    """Raised when a pipeline stage fails."""
    pass


class StageTimeoutError(StageError):
    """Raised when an external command exceeds timeout."""
    pass


class ClipWorker:
    """
    Stateless worker process. Pulls jobs from Redis, processes them
    through the 6-stage pipeline, and writes results to S3 + PostgreSQL.
    """

    STAGES = ["download", "danmaku", "asr", "scoring", "clipping", "upload"]
    MAX_RETRIES = 3
    DEFAULT_CMD_TIMEOUT_SEC = int(os.getenv("WORKER_CMD_TIMEOUT_SEC", "1200"))
    YTDLP_TIMEOUT_SEC = int(os.getenv("WORKER_YTDLP_TIMEOUT_SEC", "900"))
    FFMPEG_TIMEOUT_SEC = int(os.getenv("WORKER_FFMPEG_TIMEOUT_SEC", "900"))
    FFPROBE_TIMEOUT_SEC = int(os.getenv("WORKER_FFPROBE_TIMEOUT_SEC", "30"))
    CMD_RETRIES = int(os.getenv("WORKER_CMD_RETRIES", "2"))

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        inference_url: str = "http://localhost:8001",
    ):
        self.worker_id = f"worker-{uuid.uuid4().hex[:8]}"
        self.queue = JobQueue(redis_url)
        self.storage = S3Storage()
        self.inference = InferenceClient(inference_url)
        self._ranker_model_cache: Optional[Dict[str, Any]] = None
        self._ranker_model_mtime: Optional[float] = None
        logger.info("Worker %s initialized", self.worker_id)

    def run(self) -> None:
        """Main loop: pull jobs and process them."""
        logger.info("Worker %s starting main loop", self.worker_id)
        while True:
            payload = self.queue.dequeue(self.worker_id, timeout=5)
            if payload is None:
                continue

            job_id = payload["job_id"]

            # Skip cleanup/maintenance jobs
            if job_id.startswith("cleanup:"):
                self._handle_cleanup(job_id.split(":", 1)[1])
                self.queue.complete(self.worker_id)
                continue

            self._process_job(uuid.UUID(job_id))

    def _process_job(self, job_id: uuid.UUID) -> None:
        """Execute all pipeline stages for a job."""
        with get_sync_db() as db:
            job = get_job_sync(db, job_id)
            if not job or job.status == JobStatus.CANCELLED:
                self.queue.complete(self.worker_id)
                return

            # Mark as processing
            job.status = JobStatus.PROCESSING
            job.started_at = datetime.now(timezone.utc)
            job.worker_id = self.worker_id
            db.commit()

            try:
                # Determine start stage from checkpoint
                start_idx = 0
                if job.checkpoint_stage and job.checkpoint_stage in self.STAGES:
                    start_idx = self.STAGES.index(job.checkpoint_stage) + 1

                context: Dict[str, Any] = (
                    dict(job.checkpoint_data) if job.checkpoint_data else {}
                )
                config = dict(job.config) if job.config else {}

                stage_fns = {
                    "download": self._stage_download,
                    "danmaku": self._stage_danmaku,
                    "asr": self._stage_asr,
                    "scoring": self._stage_scoring,
                    "clipping": self._stage_clipping,
                    "upload": self._stage_upload,
                }

                for i in range(start_idx, len(self.STAGES)):
                    stage = self.STAGES[i]
                    progress = i / len(self.STAGES)
                    self.queue.publish_progress(str(job_id), stage, progress)

                    job.current_stage = stage
                    job.progress = progress
                    db.commit()

                    logger.info("Job %s: stage %s (%d/%d)",
                                job_id, stage, i + 1, len(self.STAGES))

                    context = stage_fns[stage](job, config, context, db)

                    # Checkpoint
                    job.checkpoint_stage = stage
                    job.checkpoint_data = context
                    db.commit()

                # Success
                job.status = JobStatus.COMPLETED
                job.completed_at = datetime.now(timezone.utc)
                job.progress = 1.0
                db.commit()

                self.queue.publish_progress(str(job_id), "completed", 1.0)
                self.queue.complete(self.worker_id)
                logger.info("Job %s completed successfully", job_id)

            except Exception as e:
                logger.exception("Job %s failed at stage %s", job_id, job.current_stage)
                self._handle_failure(job, db, e)
                self.queue.fail(self.worker_id)

    def _is_enabled_flag(self, value: Any, default: bool = True) -> bool:
        return parse_bool(value, default)

    def _resolve_feedback_model_path(self, config: dict) -> Path:
        from_config = str(config.get("feedback_model_path", "") or "").strip()
        from_env = str(os.getenv("FEEDBACK_RANKER_PATH", "") or "").strip()
        raw = from_config or from_env
        if raw:
            path = Path(raw).expanduser()
            return path if path.is_absolute() else (Path.cwd() / path).resolve()
        return default_model_path()

    def _resolve_boundary_profile_path(self, config: dict) -> Path:
        from_config = str(config.get("boundary_profile_path", "") or "").strip()
        from_env = str(os.getenv("BOUNDARY_PROFILE_PATH", "") or "").strip()
        raw = from_config or from_env
        if raw:
            path = Path(raw).expanduser()
            return path if path.is_absolute() else (Path.cwd() / path).resolve()
        return (
            Path(os.getenv("OUTPUT_DIR", "./output")) / "_api_jobs" / "_feedback" / "boundary_profile.json"
        ).resolve()

    def _load_feedback_ranker_model(self, config: dict) -> Optional[Dict[str, Any]]:
        env_enabled = self._is_enabled_flag(os.getenv("ENABLE_FEEDBACK_RANKING", "1"), True)
        cfg_enabled = self._is_enabled_flag(config.get("feedback_rank"), True)
        if not env_enabled or not cfg_enabled:
            return None

        model_path = self._resolve_feedback_model_path(config)
        if not model_path.exists():
            self._ranker_model_cache = None
            self._ranker_model_mtime = None
            return None

        try:
            mtime = model_path.stat().st_mtime
        except OSError:
            return None

        if (
            self._ranker_model_cache is not None
            and self._ranker_model_mtime is not None
            and abs(self._ranker_model_mtime - mtime) < 1e-6
        ):
            return self._ranker_model_cache

        model = load_feedback_model(model_path)
        if model:
            self._ranker_model_cache = model
            self._ranker_model_mtime = mtime
            logger.info(
                "Loaded feedback ranker model from %s (n=%s)",
                model_path,
                model.get("n_samples", "?"),
            )
        else:
            self._ranker_model_cache = None
            self._ranker_model_mtime = None
        return model

    def _build_llm_rerank_config(self, config: dict) -> LLMRerankConfig:
        env_enabled = self._is_enabled_flag(os.getenv("ENABLE_LLM_RERANK", "0"), False)
        cfg_enabled = self._is_enabled_flag(config.get("llm_rerank"), env_enabled)

        model_raw = str(config.get("llm_model", "") or "").strip() or None

        max_candidates: Optional[int] = None
        if config.get("llm_max_candidates") is not None:
            try:
                max_candidates = int(config.get("llm_max_candidates"))
            except (TypeError, ValueError):
                max_candidates = None

        score_weight: Optional[float] = None
        if config.get("llm_score_weight") is not None:
            try:
                score_weight = float(config.get("llm_score_weight"))
            except (TypeError, ValueError):
                score_weight = None

        timeout_sec: Optional[float] = None
        if config.get("llm_timeout_sec") is not None:
            try:
                timeout_sec = float(config.get("llm_timeout_sec"))
            except (TypeError, ValueError):
                timeout_sec = None

        return LLMRerankConfig.from_env(
            enabled=cfg_enabled,
            model=model_raw,
            max_candidates=max_candidates,
            score_weight=score_weight,
            timeout_sec=timeout_sec,
        )

    def _build_semantic_config(self, config: dict) -> LLMRerankConfig:
        env_enabled = self._is_enabled_flag(os.getenv("ENABLE_SEMANTIC_ENRICHMENT", "0"), False)
        cfg_enabled = self._is_enabled_flag(config.get("semantic_enrichment"), env_enabled)

        model_raw = (
            str(config.get("semantic_model", "") or "").strip()
            or str(config.get("llm_model", "") or "").strip()
            or str(os.getenv("SEMANTIC_MODEL", "") or "").strip()
            or None
        )

        max_candidates: Optional[int] = None
        if config.get("semantic_max_candidates") is not None:
            try:
                max_candidates = int(config.get("semantic_max_candidates"))
            except (TypeError, ValueError):
                max_candidates = None
        elif str(os.getenv("SEMANTIC_MAX_CANDIDATES", "") or "").strip():
            try:
                max_candidates = int(os.getenv("SEMANTIC_MAX_CANDIDATES", "8"))
            except (TypeError, ValueError):
                max_candidates = None

        score_weight: Optional[float] = None
        if config.get("semantic_score_weight") is not None:
            try:
                score_weight = float(config.get("semantic_score_weight"))
            except (TypeError, ValueError):
                score_weight = None
        elif str(os.getenv("SEMANTIC_SCORE_WEIGHT", "") or "").strip():
            try:
                score_weight = float(os.getenv("SEMANTIC_SCORE_WEIGHT", "0.2"))
            except (TypeError, ValueError):
                score_weight = None

        timeout_sec: Optional[float] = None
        if config.get("semantic_timeout_sec") is not None:
            try:
                timeout_sec = float(config.get("semantic_timeout_sec"))
            except (TypeError, ValueError):
                timeout_sec = None
        elif str(os.getenv("SEMANTIC_TIMEOUT_SEC", "") or "").strip():
            try:
                timeout_sec = float(os.getenv("SEMANTIC_TIMEOUT_SEC", "30"))
            except (TypeError, ValueError):
                timeout_sec = None

        return LLMRerankConfig.from_env(
            enabled=cfg_enabled,
            model=model_raw,
            max_candidates=max_candidates if max_candidates is not None else 8,
            score_weight=score_weight if score_weight is not None else 0.2,
            timeout_sec=timeout_sec if timeout_sec is not None else 30.0,
        )

    @staticmethod
    def _excerpt_window(
        clip_start: float,
        clip_end: float,
        comments_data: List[Dict[str, Any]],
        segments_data: List[Dict[str, Any]],
    ) -> tuple[str, str]:
        danmaku_texts = [
            str(c.get("text", ""))
            for c in comments_data
            if clip_start <= float(c.get("time_offset", 0.0)) <= clip_end
        ][:24]
        asr_texts = [
            str(s.get("text", "")).strip()
            for s in segments_data
            if float(s.get("start", 0.0)) < clip_end and float(s.get("end", 0.0)) > clip_start
        ][:14]
        return " | ".join(t for t in danmaku_texts if t), " ".join(t for t in asr_texts if t)

    def _build_llm_candidates(
        self,
        merged: List[Dict[str, Any]],
        comments_data: List[Dict[str, Any]],
        segments_data: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for idx, item in enumerate(merged):
            clip_start = float(item.get("clip_start", 0.0))
            clip_end = float(item.get("clip_end", 0.0))
            danmaku_excerpt, asr_excerpt = self._excerpt_window(
                clip_start,
                clip_end,
                comments_data,
                segments_data,
            )
            candidates.append(
                {
                    "index": idx,
                    "clip_start": clip_start,
                    "clip_end": clip_end,
                    "duration": max(0.0, clip_end - clip_start),
                    "score": float(item.get("score", 0.0)),
                    "base_rank_score": float(item.get("rank_score", item.get("score", 0.0))),
                    "virality_score": item.get("virality_score"),
                    "danmaku_count": int(item.get("danmaku_count", 0) or 0),
                    "top_keywords": list(item.get("top_keywords", []) or [])[:8],
                    "danmaku_excerpt": danmaku_excerpt,
                    "asr_excerpt": asr_excerpt,
                }
            )
        return candidates

    def _apply_llm_candidate_analysis(
        self,
        merged: List[Dict[str, Any]],
        comments_data: List[Dict[str, Any]],
        segments_data: List[Dict[str, Any]],
        config: dict,
    ) -> tuple[bool, bool]:
        llm_cfg = self._build_llm_rerank_config(config)
        semantic_cfg = self._build_semantic_config(config)
        if not llm_cfg.enabled and not semantic_cfg.enabled:
            return False, False

        analysis_cfg = LLMRerankConfig.from_env(
            enabled=True,
            model=llm_cfg.model or semantic_cfg.model,
            max_candidates=max(
                llm_cfg.max_candidates if llm_cfg.enabled else 0,
                semantic_cfg.max_candidates if semantic_cfg.enabled else 0,
            ),
            score_weight=llm_cfg.score_weight if llm_cfg.enabled else semantic_cfg.score_weight,
            timeout_sec=max(
                llm_cfg.timeout_sec if llm_cfg.enabled else 0.0,
                semantic_cfg.timeout_sec if semantic_cfg.enabled else 0.0,
            ),
        )

        candidates = self._build_llm_candidates(merged, comments_data, segments_data)

        try:
            analyses = analyze_candidates_with_llm(candidates, analysis_cfg)
        except Exception as exc:
            logger.warning("LLM candidate analysis unavailable, fallback to base ranking: %s", exc)
            return False, False

        if not analyses:
            return False, False

        semantic_applied = False
        llm_applied = False
        for idx, item in enumerate(merged):
            analysis = analyses.get(idx)
            if not analysis:
                continue
            semantic_score = float(analysis.get("score", 0.0))
            item["semantic_score"] = semantic_score
            item["content_summary"] = str(
                analysis.get("summary")
                or analysis.get("title")
                or item.get("content_summary")
                or ""
            ).strip()[:240]
            item["content_tags"] = list(analysis.get("tags", []) or [])[:6]
            item["content_hook"] = bool(analysis.get("hook", False))
            semantic_applied = True

            if llm_cfg.enabled:
                item["llm_score"] = semantic_score
                item["llm_title"] = analysis.get("title")
                item["llm_reason"] = analysis.get("reason")
                item["rank_score"] = (
                    (1.0 - llm_cfg.score_weight) * float(item.get("rank_score", 0.0))
                    + llm_cfg.score_weight * semantic_score
                )
                llm_applied = True
            elif semantic_cfg.enabled:
                item["rank_score"] = (
                    (1.0 - semantic_cfg.score_weight) * float(item.get("rank_score", 0.0))
                    + semantic_cfg.score_weight * semantic_score
                )

        return llm_applied, semantic_applied

    # ===================================================================
    # Pipeline stages
    # ===================================================================

    def _stage_download(self, job: Job, config: dict,
                        context: dict, db) -> dict:
        """Download video from source, upload raw to S3."""
        if job.source_type == "bili_vod" and job.source_url:
            local_path = self._download_bili_vod_with_ytdlp(job.source_url)
            duration = self._probe_duration(local_path)
        elif job.source_type == "web_vod" and job.source_url:
            local_path = self._download_web_vod_with_ytdlp(
                job.source_url,
                proxy=config.get("proxy") or os.getenv("HTTPS_PROXY"),
            )
            duration = self._probe_duration(local_path)
        elif job.source_type == "bili_live" and job.source_url:
            from stream_clipper.ingest.bili_live import BiliLiveIngest

            ingest = BiliLiveIngest(
                url=job.source_url,
                max_seconds=int(config.get("duration", 1800)),
            )
            ingest_result = ingest.run()
            local_path = str(ingest_result.video_path)
            duration = float(ingest_result.duration)
            prefetched_comments = [
                {
                    "time_offset": c.time_offset,
                    "text": c.text,
                    "user_id": c.user_id,
                    "dtype": c.dtype,
                }
                for c in ingest_result.comments
            ]
            prefetch_key = f"danmaku/{job.user_id}/{job.id}/live_prefetch_comments.json"
            self.storage.upload_json(prefetched_comments, prefetch_key)
            context["prefetched_comments_s3_key"] = prefetch_key
        elif job.source_type == "web_live" and job.source_url:
            from stream_clipper.ingest.web_video import WebLiveIngest

            ingest = WebLiveIngest(
                url=job.source_url,
                max_seconds=int(config.get("duration", 1800)),
                proxy=config.get("proxy") or os.getenv("HTTPS_PROXY"),
            )
            ingest_result = ingest.run()
            local_path = str(ingest_result.video_path)
            duration = float(ingest_result.duration)
        elif job.source_type == "local":
            s3_key = context.get("raw_s3_key") or config.get("raw_s3_key", "")
            if not s3_key:
                raise StageError("本地上传任务缺少 raw_s3_key 上下文")
            local_path = self.storage.download_temp(s3_key, suffix=".mp4")
            duration = self._probe_duration(local_path)
        else:
            raise StageError(f"不支持的 source_type：{job.source_type}")

        # Upload raw to S3
        raw_key = f"raw/{job.user_id}/{job.id}/source.mp4"
        self.storage.upload_file(local_path, raw_key, content_type="video/mp4")

        job.raw_video_s3_key = raw_key
        job.video_duration = duration

        context["local_video_path"] = local_path
        local_video_dir = str(Path(local_path).parent)
        if Path(local_video_dir).name.startswith("stream_clipper_vod_"):
            context["local_video_dir"] = local_video_dir
        context["raw_s3_key"] = raw_key
        context["duration"] = duration
        return context

    def _stage_danmaku(self, job: Job, config: dict,
                       context: dict, db) -> dict:
        """Fetch and parse danmaku comments."""
        from stream_clipper.danmaku.parser import parse_xml

        comments_data = []

        if job.source_type == "bili_vod" and job.source_url:
            # Use ingest module to fetch danmaku
            try:
                from stream_clipper.ingest.bili_vod import (
                    BiliVodIngest,
                    _download_danmaku,
                    _extract_bvid,
                    _fetch_video_info,
                )
                ingest = BiliVodIngest(
                    url=job.source_url,
                    sessdata=os.getenv("BILI_SESSDATA"),
                )
                comments = []
                if hasattr(ingest, "fetch_danmaku"):
                    comments = ingest.fetch_danmaku(job.source_url)
                else:
                    bvid = _extract_bvid(job.source_url)
                    cookies = {}
                    sessdata = os.getenv("BILI_SESSDATA")
                    if sessdata:
                        cookies["SESSDATA"] = sessdata
                    info = _fetch_video_info(bvid, cookies) if bvid else None
                    cid = info.get("cid") if info else None
                    if cid:
                        with tempfile.TemporaryDirectory(prefix="stream_clipper_dm_") as tmp_dir:
                            xml_path = _download_danmaku(
                                cid,
                                Path(tmp_dir),
                                str(info.get("title", bvid or "video")),
                            )
                            if xml_path:
                                comments = parse_xml(str(xml_path))
                comments_data = [
                    {"time_offset": c.time_offset, "text": c.text,
                     "user_id": c.user_id, "dtype": c.dtype}
                    for c in comments
                ]
            except Exception as e:
                logger.warning("Failed to fetch danmaku: %s (continuing without)", e)
        elif job.source_type == "bili_live":
            prefetch_key = context.get("prefetched_comments_s3_key")
            if prefetch_key:
                comments_data = self.storage.download_json(prefetch_key)
            else:
                comments_data = []
        elif job.source_type in {"web_vod", "web_live"}:
            comments_data = []

        elif context.get("danmaku_s3_key"):
            xml_path = self.storage.download_temp(context["danmaku_s3_key"], suffix=".xml")
            comments = parse_xml(xml_path)
            comments_data = [
                {"time_offset": c.time_offset, "text": c.text,
                 "user_id": c.user_id, "dtype": c.dtype}
                for c in comments
            ]
            os.unlink(xml_path)

        # Store parsed danmaku in S3
        danmaku_key = f"danmaku/{job.user_id}/{job.id}/comments.json"
        self.storage.upload_json(comments_data, danmaku_key)

        context["danmaku_s3_key"] = danmaku_key
        context["danmaku_count"] = len(comments_data)
        return context

    def _stage_asr(self, job: Job, config: dict,
                   context: dict, db) -> dict:
        """Extract audio and call inference service for ASR."""
        local_video = context["local_video_path"]

        # Extract audio
        audio_path = self._extract_audio(local_video)
        audio_energy_values: List[float] = []
        try:
            audio_energy = compute_rms_energy_per_second(audio_path)
            audio_energy_values = [float(x) for x in audio_energy.tolist()]
        except Exception as exc:
            logger.warning("Audio energy extraction skipped: %s", exc)

        # Upload audio to S3 for inference service
        audio_key = f"temp/{job.id}/audio.wav"
        uploaded_audio = False
        try:
            self.storage.upload_file(audio_path, audio_key, content_type="audio/wav")
            uploaded_audio = True
            job.audio_s3_key = audio_key

            # Call inference service
            segments = self.inference.transcribe(audio_key)
        finally:
            if os.path.exists(audio_path):
                os.unlink(audio_path)
            if uploaded_audio:
                try:
                    self.storage.delete(audio_key)
                except Exception as exc:
                    logger.warning("Failed to delete temp ASR audio %s: %s", audio_key, exc)
            job.audio_s3_key = None

        # Store segments
        segments_key = f"asr/{job.user_id}/{job.id}/segments.json"
        self.storage.upload_json(segments, segments_key)

        if audio_energy_values:
            energy_key = f"features/{job.user_id}/{job.id}/audio_energy.json"
            self.storage.upload_json({"energy": audio_energy_values}, energy_key)
            context["audio_energy_s3_key"] = energy_key

        # Record usage
        duration_minutes = context.get("duration", 0) / 60.0
        record_usage_sync(db, job.user_id, "asr_minutes", duration_minutes, job.id)

        context["segments_s3_key"] = segments_key
        context["segment_count"] = len(segments)
        return context

    def _stage_scoring(self, job: Job, config: dict,
                       context: dict, db) -> dict:
        """Run resonance scoring and peak detection."""
        from stream_clipper.danmaku.models import DanmakuComment
        from stream_clipper.asr.transcriber import Segment
        from stream_clipper.resonance.scorer import compute_scores
        from stream_clipper.resonance.peaks import find_highlights

        # Load data from S3
        comments_data = self.storage.download_json(context["danmaku_s3_key"])
        segments_data = self.storage.download_json(context["segments_s3_key"])
        audio_energy_values: Optional[List[float]] = None
        audio_energy_s3_key = context.get("audio_energy_s3_key")
        if audio_energy_s3_key:
            try:
                energy_blob = self.storage.download_json(audio_energy_s3_key)
                if isinstance(energy_blob, dict):
                    raw = energy_blob.get("energy", [])
                else:
                    raw = energy_blob
                if isinstance(raw, list):
                    audio_energy_values = [float(x) for x in raw]
            except Exception as exc:
                logger.warning("Failed to load audio energy signal: %s", exc)

        comments = [
            DanmakuComment(
                time_offset=c["time_offset"], text=c["text"],
                user_id=c.get("user_id", ""), dtype=c.get("dtype", 1)
            )
            for c in comments_data
        ]
        segments = [
            Segment(start=s["start"], end=s["end"], text=s["text"])
            for s in segments_data
        ]
        duration = context["duration"]
        top_n = max(1, int(config.get("top_n", 10)))
        candidate_multiplier = max(1, int(config.get("candidate_multiplier", 3)))
        clip_window = resolve_clip_window(
            config.get("clip_duration", 45.0),
            adaptive_min_before=float(config.get("adaptive_min_before", 5.0)),
            adaptive_max_before=_optional_float(config.get("adaptive_max_before")),
            adaptive_min_after=float(config.get("adaptive_min_after", 8.0)),
            adaptive_max_after=_optional_float(config.get("adaptive_max_after")),
        )
        clip_duration = clip_window["clip_duration"]
        pad_before = clip_window["pad_before"]
        pad_after = clip_window["pad_after"]
        min_gap = max(5.0, min(3600.0, float(config.get("min_gap", max(clip_duration * 0.8, 10.0)))))

        # Score
        times, scores = compute_scores(
            comments,
            segments,
            duration,
            audio_energy=audio_energy_values,
        )

        # Detect peaks — cast a wider net for later filtering
        highlights = find_highlights(
            times, scores, comments,
            top_n=top_n * candidate_multiplier,
            pad_before=pad_before,
            pad_after=pad_after,
            min_gap=min_gap,
            video_duration=duration,
            adaptive_padding=self._is_enabled_flag(config.get("adaptive_padding", True), True),
            half_peak_ratio=float(config.get("half_peak_ratio", 0.5)),
            adaptive_min_before=clip_window["adaptive_min_before"],
            adaptive_max_before=clip_window["adaptive_max_before"],
            adaptive_min_after=clip_window["adaptive_min_after"],
            adaptive_max_after=clip_window["adaptive_max_after"],
        )

        virality_scores: List[Dict[str, float]] = []
        if highlights:
            try:
                windows = [
                    {"start": h.clip_start, "end": h.clip_end}
                    for h in highlights
                ]
                virality_scores = self.inference.predict_virality(
                    segments_s3_key=context["segments_s3_key"],
                    danmaku_s3_key=context["danmaku_s3_key"],
                    highlights=windows,
                )
            except Exception as e:
                logger.warning("Virality inference unavailable, fallback to resonance-only ranking: %s", e)

        ranker_model = self._load_feedback_ranker_model(config)

        merged = []
        for idx, h in enumerate(highlights):
            v = virality_scores[idx] if idx < len(virality_scores) else {}
            virality = float(v.get("composite", 0.0)) if v else 0.0
            features = extract_features(
                {
                    "score": h.score,
                    "danmaku_count": h.danmaku_count,
                    "top_keywords": h.top_keywords,
                    "duration": (h.clip_end - h.clip_start),
                    "virality_score": (virality if v else None),
                }
            )
            feedback_rank_score = (
                predict_quality(features, ranker_model) if ranker_model else None
            )
            merged.append(
                {
                    "clip_start": h.clip_start,
                    "clip_end": h.clip_end,
                    "peak_time": h.peak_time,
                    "score": h.score,
                    "danmaku_count": h.danmaku_count,
                    "top_keywords": h.top_keywords,
                    "virality_score": virality if v else None,
                    "predicted_ctr": (float(v.get("predicted_ctr", 0.0)) if v else None),
                    "predicted_share": (float(v.get("predicted_share", 0.0)) if v else None),
                    "feedback_rank_score": feedback_rank_score,
                    "llm_score": None,
                    "llm_title": None,
                    "llm_reason": None,
                    "semantic_score": None,
                    "content_summary": None,
                    "content_tags": [],
                    "content_hook": False,
                    "rank_score": (
                        float(feedback_rank_score)
                        if feedback_rank_score is not None
                        else (
                            0.6 * h.score + 0.4 * virality
                            if (config.get("viral_rank") and v)
                            else h.score
                        )
                    ),
                }
            )

        llm_applied, semantic_applied = self._apply_llm_candidate_analysis(
            merged,
            comments_data=comments_data,
            segments_data=segments_data,
            config=config,
        )

        # Take final top-N by rank score then return chronological output
        highlights_ranked = sorted(merged, key=lambda h: h["rank_score"], reverse=True)[:top_n]
        highlights_ranked.sort(key=lambda h: h["clip_start"])

        boundary_enabled = self._is_enabled_flag(os.getenv("ENABLE_BOUNDARY_ADAPTATION", "1"), True) and self._is_enabled_flag(
            config.get("boundary_adaptation", True),
            True,
        )
        boundary_profile = None
        if boundary_enabled:
            try:
                boundary_profile = load_boundary_profile(self._resolve_boundary_profile_path(config))
            except Exception as e:
                logger.warning("Failed to load boundary profile: %s", e)
                boundary_profile = None

        ai_bounds: List[tuple[float, float]] = [
            (float(h["clip_start"]), float(h["clip_end"])) for h in highlights_ranked
        ]
        if boundary_profile is not None:
            adapted = []
            for h in highlights_ranked:
                ns, ne = apply_boundary_adaptation(
                    float(h["clip_start"]),
                    float(h["clip_end"]),
                    video_duration=float(duration),
                    profile=boundary_profile,
                    min_duration=5.0,
                )
                h2 = dict(h)
                h2["clip_start"] = ns
                h2["clip_end"] = ne
                adapted.append(h2)
            highlights_ranked = adapted

        if llm_applied and ranker_model:
            context["ranking_source"] = "llm+feedback_model"
        elif llm_applied:
            context["ranking_source"] = "llm+virality" if config.get("viral_rank") else "llm+resonance"
        elif semantic_applied and ranker_model:
            context["ranking_source"] = "semantic+feedback_model"
        elif semantic_applied:
            context["ranking_source"] = "semantic+virality" if config.get("viral_rank") else "semantic+resonance"
        else:
            context["ranking_source"] = (
                "feedback_model" if ranker_model else ("virality" if config.get("viral_rank") else "resonance")
            )
        context["llm_rerank_applied"] = bool(llm_applied)
        context["semantic_enrichment_applied"] = bool(semantic_applied)
        context["boundary_adaptation"] = (
            {
                "enabled": True,
                "count": int((boundary_profile or {}).get("count", 0)),
                "mean_start_delta": float((boundary_profile or {}).get("mean_start_delta", 0.0)),
                "mean_end_delta": float((boundary_profile or {}).get("mean_end_delta", 0.0)),
            }
            if boundary_profile is not None
            else {"enabled": False}
        )

        context["highlights"] = [
            {
                "ai_clip_start": ai_bounds[i][0] if i < len(ai_bounds) else h["clip_start"],
                "ai_clip_end": ai_bounds[i][1] if i < len(ai_bounds) else h["clip_end"],
                "clip_start": h["clip_start"],
                "clip_end": h["clip_end"],
                "peak_time": h["peak_time"],
                "score": h["score"],
                "rank_score": h["rank_score"],
                "feedback_rank_score": h["feedback_rank_score"],
                "llm_score": h.get("llm_score"),
                "llm_title": h.get("llm_title"),
                "llm_reason": h.get("llm_reason"),
                "semantic_score": h.get("semantic_score"),
                "content_summary": h.get("content_summary"),
                "content_tags": h.get("content_tags", []),
                "content_hook": h.get("content_hook", False),
                "danmaku_count": h["danmaku_count"],
                "top_keywords": h["top_keywords"],
                "virality_score": h["virality_score"],
                "predicted_ctr": h["predicted_ctr"],
                "predicted_share": h["predicted_share"],
            }
            for i, h in enumerate(highlights_ranked)
        ]
        return context

    def _stage_clipping(self, job: Job, config: dict,
                        context: dict, db) -> dict:
        """Cut clips with FFmpeg."""
        video_path = Path(context["local_video_path"])
        clip_temp_dir = Path(
            tempfile.mkdtemp(prefix=f"stream_clipper_{str(job.id).replace('-', '')[:12]}_clips_")
        )
        context["clip_temp_dir"] = str(clip_temp_dir)

        highlights = [
            Highlight(
                clip_start=float(h["clip_start"]),
                clip_end=float(h["clip_end"]),
                peak_time=float(h["peak_time"]),
                score=float(h["score"]),
                danmaku_count=int(h["danmaku_count"]),
                top_keywords=list(h.get("top_keywords", [])),
            )
            for h in context["highlights"]
        ]

        clips = []
        try:
            clip_results = cut_clips_indexed(
                video_path,
                highlights,
                clip_temp_dir,
                title=f"job_{str(job.id)[:8]}",
            )
            for idx, output_path in clip_results:
                clips.append({
                    "local_path": str(output_path),
                    "index": idx,
                    **context["highlights"][idx],
                })
        except Exception:
            shutil.rmtree(clip_temp_dir, ignore_errors=True)
            context.pop("clip_temp_dir", None)
            raise

        context["clip_files"] = clips
        return context

    def _stage_upload(self, job: Job, config: dict,
                      context: dict, db) -> dict:
        """Upload clips and thumbnails to S3, create DB records."""
        for clip_data in context.get("clip_files", []):
            idx = clip_data["index"]
            local_path = clip_data["local_path"]

            if not os.path.exists(local_path):
                continue

            # Upload clip
            s3_key = f"clips/{job.user_id}/{job.id}/{idx:03d}.mp4"
            self.storage.upload_file(local_path, s3_key, content_type="video/mp4")
            file_size = os.path.getsize(local_path)

            # Generate and upload thumbnail
            thumb_path = local_path.replace(".mp4", ".jpg")
            thumb_key = f"thumbnails/{job.user_id}/{job.id}/{idx:03d}.jpg"
            self._generate_thumbnail(local_path, thumb_path)
            if os.path.exists(thumb_path):
                self.storage.upload_file(thumb_path, thumb_key, content_type="image/jpeg")
                os.unlink(thumb_path)
            else:
                thumb_key = None

            # Create DB record
            create_clip_sync(
                db,
                job_id=job.id,
                user_id=job.user_id,
                s3_key=s3_key,
                thumbnail_s3_key=thumb_key,
                file_size_bytes=file_size,
                clip_start=clip_data["clip_start"],
                clip_end=clip_data["clip_end"],
                duration=clip_data["clip_end"] - clip_data["clip_start"],
                highlight_score=clip_data.get("score"),
                virality_score=clip_data.get("virality_score"),
                transcript=clip_data.get("content_summary"),
                predicted_ctr=clip_data.get("predicted_ctr"),
                predicted_share=clip_data.get("predicted_share"),
                danmaku_count=clip_data.get("danmaku_count"),
                top_keywords=clip_data.get("top_keywords"),
            )

            # Record storage usage
            record_usage_sync(
                db, job.user_id, "clip_storage_mb",
                file_size / (1024 * 1024), job.id
            )

            # Cleanup local
            os.unlink(local_path)

        db.commit()

        # Cleanup temp video + any remaining clip artifacts
        self._cleanup_context_artifacts(context, include_video=True)

        context["uploaded"] = True
        return context

    # ===================================================================
    # Failure handling
    # ===================================================================

    def _handle_failure(self, job: Job, db, error: Exception) -> None:
        job.retry_count = (job.retry_count or 0) + 1
        job.last_error = traceback.format_exc()

        if job.retry_count <= self.MAX_RETRIES:
            job.status = JobStatus.RETRYING
            db.commit()

            delay = self.queue.schedule_retry(
                str(job.id), job.retry_count,
                priority=job.config.get("priority", "normal") if job.config else "normal",
            )
            logger.info("Job %s: retry #%d scheduled in %ds",
                        job.id, job.retry_count, delay)
        else:
            job.status = JobStatus.FAILED
            job.error_message = str(error)
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            self._cleanup_context_artifacts(job.checkpoint_data or {}, include_video=True)

            self.queue.dead_letter(str(job.id), str(error))
            logger.error("Job %s failed permanently after %d retries",
                         job.id, self.MAX_RETRIES)

    # ===================================================================
    # Helpers
    # ===================================================================

    @staticmethod
    def _normalize_bili_url(raw: str) -> str:
        s = (raw or "").strip()
        if not s:
            return s
        if s.startswith("BV"):
            return f"https://www.bilibili.com/video/{s}"
        parsed = urlparse(s)
        if not parsed.scheme and "bilibili.com" in s:
            return f"https://{s.lstrip('/')}"
        return s

    def _cleanup_context_artifacts(self, context: dict, *, include_video: bool) -> None:
        for clip in context.get("clip_files", []) or []:
            local_path = str(clip.get("local_path", "") or "").strip()
            if local_path and os.path.exists(local_path):
                try:
                    os.unlink(local_path)
                except OSError as exc:
                    logger.warning("Failed to delete temp clip %s: %s", local_path, exc)

        clip_temp_dir = str(context.get("clip_temp_dir", "") or "").strip()
        if clip_temp_dir:
            shutil.rmtree(clip_temp_dir, ignore_errors=True)

        if include_video:
            local_video = str(context.get("local_video_path", "") or "").strip()
            if local_video and os.path.exists(local_video):
                try:
                    os.unlink(local_video)
                except OSError as exc:
                    logger.warning("Failed to delete temp source video %s: %s", local_video, exc)
            local_video_dir = str(context.get("local_video_dir", "") or "").strip()
            if local_video_dir and Path(local_video_dir).name.startswith("stream_clipper_vod_"):
                shutil.rmtree(local_video_dir, ignore_errors=True)

    def _run_command(
        self,
        cmd: List[str],
        *,
        timeout_sec: int,
        retries: Optional[int] = None,
        text: bool = False,
    ) -> subprocess.CompletedProcess:
        """Run subprocess with timeout + bounded retry, return completed process."""
        max_retries = self.CMD_RETRIES if retries is None else max(0, retries)
        cmd_preview = " ".join(cmd[:4]) + (" ..." if len(cmd) > 4 else "")

        for attempt in range(max_retries + 1):
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=text,
                    timeout=timeout_sec,
                )
            except subprocess.TimeoutExpired as exc:
                if attempt < max_retries:
                    backoff = min(8.0, 1.5 ** attempt)
                    logger.warning(
                        "Command timeout (attempt %d/%d): %s; retry in %.1fs",
                        attempt + 1,
                        max_retries + 1,
                        cmd_preview,
                        backoff,
                    )
                    time.sleep(backoff)
                    continue
                raise StageTimeoutError(
                    f"命令执行超时（{timeout_sec}秒）：{cmd_preview}"
                ) from exc

            if result.returncode == 0:
                return result

            if attempt < max_retries:
                backoff = min(8.0, 1.5 ** attempt)
                logger.warning(
                    "Command failed (attempt %d/%d): %s rc=%d; retry in %.1fs",
                    attempt + 1,
                    max_retries + 1,
                    cmd_preview,
                    result.returncode,
                    backoff,
                )
                time.sleep(backoff)
                continue

            raise StageError(
                f"命令执行失败（rc={result.returncode}）："
                f"{safe_decode(result.stderr)[-500:]}"
            )

        raise StageError(f"出现异常命令失败状态：{cmd_preview}")

    def _download_bili_vod_with_ytdlp(self, url: str) -> str:
        from stream_clipper.ingest.bili_vod import _download_video

        ensure_ytdlp_ready()
        dest_dir = Path(tempfile.mkdtemp(prefix="stream_clipper_vod_"))
        video_path = _download_video(
            self._normalize_bili_url(url),
            dest_dir,
            cookies_file=(str(os.getenv("BILI_COOKIES_FILE", "") or "").strip() or None),
        )
        return str(video_path)

    def _download_web_vod_with_ytdlp(self, url: str, proxy: Optional[str] = None) -> str:
        from stream_clipper.ingest.web_video import download_video, normalize_web_url

        ensure_ytdlp_ready()
        dest_dir = Path(tempfile.mkdtemp(prefix="stream_clipper_web_vod_"))
        video_path = download_video(
            normalize_web_url(url),
            dest_dir,
            proxy=(str(proxy or "").strip() or None),
            timeout_sec=self.YTDLP_TIMEOUT_SEC,
        )
        return str(video_path)

    def _extract_audio(self, video_path: str) -> str:
        audio_path = os.path.join(
            tempfile.gettempdir(), f"audio_{uuid.uuid4().hex[:8]}.wav"
        )
        self._run_command([
            os.environ.get("FFMPEG_PATH", "ffmpeg"), "-y", "-i", video_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            audio_path,
        ], timeout_sec=self.FFMPEG_TIMEOUT_SEC, retries=1)
        return audio_path

    def _probe_duration(self, video_path: str) -> float:
        result = self._run_command([
            os.environ.get("FFPROBE_PATH", "ffprobe"), "-v", "quiet", "-show_entries", "format=duration",
            "-of", "json", video_path,
        ], timeout_sec=self.FFPROBE_TIMEOUT_SEC, retries=1, text=True)
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])

    def _generate_thumbnail(self, video_path: str, output_path: str) -> None:
        try:
            self._run_command([
                os.environ.get("FFMPEG_PATH", "ffmpeg"), "-y", "-i", video_path,
                "-ss", "1", "-vframes", "1",
                "-vf", "scale=320:-1",
                output_path,
            ], timeout_sec=self.FFMPEG_TIMEOUT_SEC, retries=1)
        except StageError as exc:
            logger.warning("Thumbnail generation failed for %s: %s", video_path, exc)

    def _handle_cleanup(self, clip_id: str) -> None:
        """Delete S3 objects for a soft-deleted clip."""
        with get_sync_db() as db:
            from services.db.models import Clip
            clip = db.get(Clip, uuid.UUID(clip_id))
            if clip and clip.is_deleted:
                if clip.s3_key:
                    self.storage.delete(clip.s3_key)
                if clip.thumbnail_s3_key:
                    self.storage.delete(clip.thumbnail_s3_key)
                logger.info("Cleaned up S3 objects for clip %s", clip_id)
