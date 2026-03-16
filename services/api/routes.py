"""
FastAPI route definitions for the Stream Clipper API.

Routes:
  POST /api/v1/auth/register
  POST /api/v1/auth/login
  POST /api/v1/jobs
  GET  /api/v1/jobs
  GET  /api/v1/jobs/{job_id}
  GET  /api/v1/jobs/{job_id}/stream    (SSE)
  GET  /api/v1/clips
  GET  /api/v1/clips/{clip_id}
  DELETE /api/v1/clips/{clip_id}
  POST /api/v1/upload/presign
  GET  /api/v1/admin/queue-stats
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sse_starlette.sse import EventSourceResponse
from urllib.parse import urlparse

from services.db import queries
from services.db.models import User
from services.db.session import get_async_db
from stream_clipper.ml.feedback_ranker import (
    default_model_path,
    load_jsonl,
    merge_feedback_with_adjustments,
    save_feedback_model,
    train_feedback_model,
)
from stream_clipper.ml.boundary_adaptation import update_boundary_profile

from .auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from .schemas import (
    AuthResponse,
    ClipFeedbackRequest,
    ClipFeedbackResponse,
    ClipListResponse,
    ClipResponse,
    JobCreate,
    JobListResponse,
    JobStatusResponse,
    LoginRequest,
    QueueStatsResponse,
    RegisterRequest,
    UploadUrlResponse,
)

router = APIRouter(prefix="/api/v1")
_STORAGE_SINGLETON = None
_STORAGE_LOCK = threading.Lock()


def _validate_external_source_url(source_type: str, source_url: Optional[str]) -> Optional[str]:
    if source_url is None:
        return None
    text = str(source_url).strip()
    if not text:
        return None

    if source_type == "bili_live" and text.isdigit():
        return text
    if source_type == "bili_vod" and text.startswith("BV"):
        return text

    if source_type in {"web_vod", "web_live"} and "://" not in text and "." in text:
        text = f"https://{text.lstrip('/')}"

    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(400, "source_url 必须使用 http 或 https 协议")
    return text


def _get_queue():
    try:
        from services.queue.job_queue import JobQueue
    except ModuleNotFoundError as exc:
        raise HTTPException(503, "队列后端不可用：缺少 redis 依赖") from exc
    return JobQueue(os.getenv("REDIS_URL", "redis://localhost:6379/0"))


def _get_storage():
    global _STORAGE_SINGLETON
    try:
        from services.storage.s3 import S3Storage
    except ModuleNotFoundError as exc:
        raise HTTPException(503, "对象存储后端不可用：缺少 boto3 依赖") from exc
    if _STORAGE_SINGLETON is None:
        with _STORAGE_LOCK:
            if _STORAGE_SINGLETON is None:
                _STORAGE_SINGLETON = S3Storage()
    return _STORAGE_SINGLETON


def _feedback_artifact_root() -> Path:
    return (Path(os.getenv("OUTPUT_DIR", "./output")) / "_api_jobs" / "_feedback").resolve()


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _resolve_feedback_artifact_path(
    raw_value: str,
    *,
    default_path: Path,
    label: str,
) -> Path:
    path = Path(raw_value).expanduser() if raw_value else default_path
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    else:
        path = path.resolve()

    root = _feedback_artifact_root()
    if not _is_relative_to(path, root):
        raise HTTPException(400, f"{label} must stay under {root}")
    return path


def _admin_emails() -> set[str]:
    raw = (
        str(os.getenv("FEEDBACK_RETRAIN_ADMIN_EMAILS", "") or "").strip()
        or str(os.getenv("ADMIN_EMAILS", "") or "").strip()
    )
    return {
        item.strip().lower()
        for item in raw.split(",")
        if item.strip()
    }


def _require_admin_user(user: User) -> None:
    allowed = _admin_emails()
    email = str(getattr(user, "email", "") or "").strip().lower()
    if not allowed or email not in allowed:
        raise HTTPException(403, "需要管理员权限")


@contextmanager
def _locked_file_descriptor(fd: int):
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)


def _append_jsonl_record(log_path: Path, record: Dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(str(log_path), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        with _locked_file_descriptor(fd):
            os.write(fd, payload)
    finally:
        os.close(fd)


def _feedback_log_path() -> Path:
    configured = os.getenv("FEEDBACK_LOG_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        return path
    return (Path(os.getenv("OUTPUT_DIR", "./output")) / "_api_jobs" / "_feedback" / "clip_feedback.jsonl")


def _adjustment_log_path() -> Path:
    configured = os.getenv("ADJUSTMENT_LOG_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        return path
    return (Path(os.getenv("OUTPUT_DIR", "./output")) / "_api_jobs" / "_feedback" / "clip_adjustments.jsonl")


# ===================================================================
# Auth
# ===================================================================

@router.post("/auth/register", response_model=AuthResponse, status_code=201)
async def register(body: RegisterRequest, db=Depends(get_async_db)):
    existing = await queries.get_user_by_email(db, body.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = await queries.create_user(
        db,
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
    )
    await db.commit()
    token = create_access_token(user.id)
    return AuthResponse(
        access_token=token, user_id=str(user.id), email=user.email
    )


@router.post("/auth/login", response_model=AuthResponse)
async def login(body: LoginRequest, db=Depends(get_async_db)):
    user = await queries.get_user_by_email(db, body.email)
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(user.id)
    return AuthResponse(
        access_token=token, user_id=str(user.id), email=user.email
    )


# ===================================================================
# Jobs
# ===================================================================

@router.post("/jobs", response_model=JobStatusResponse, status_code=201)
async def create_job(
    body: JobCreate,
    user: User = Depends(get_current_user),
    db=Depends(get_async_db),
):
    allowed_sources = {"local", "bili_vod", "bili_live", "web_vod", "web_live"}
    if body.source_type not in allowed_sources:
        raise HTTPException(400, f"source_type 必须是以下之一：{', '.join(sorted(allowed_sources))}")
    normalized_source_url = _validate_external_source_url(body.source_type, body.source_url)
    if body.source_type in {"bili_vod", "bili_live", "web_vod", "web_live"} and not normalized_source_url:
        raise HTTPException(400, "外部视频/直播任务必须提供 source_url")
    if body.source_type == "local" and not body.raw_s3_key:
        raise HTTPException(400, "全量 API 模式下，本地任务必须提供 raw_s3_key")

    # Enforce plan limits
    active = await queries.count_active_jobs(db, user.id)
    if active >= user.plan.max_concurrent_jobs:
        raise HTTPException(429, "Concurrent job limit reached for your plan")

    daily_mins = await queries.sum_daily_processing_minutes(db, user.id)
    if daily_mins >= user.plan.daily_minutes_limit:
        raise HTTPException(429, "Daily processing limit reached for your plan")

    job = await queries.create_job(
        db,
        user_id=user.id,
        source_type=body.source_type,
        source_url=normalized_source_url,
        config={
            "top_n": body.top_n,
            "clip_duration": body.clip_duration,
            "min_clip_duration": body.min_clip_duration,
            "max_clip_duration": body.max_clip_duration,
            "duration": body.duration,
            "raw_s3_key": body.raw_s3_key,
            "viral_rank": body.viral_rank and user.plan.viral_ranking_enabled,
            "candidate_multiplier": body.candidate_multiplier,
            "feedback_rank": body.feedback_rank,
            "feedback_model_path": body.feedback_model_path,
            "llm_rerank": body.llm_rerank,
            "llm_model": body.llm_model,
            "llm_max_candidates": body.llm_max_candidates,
            "llm_score_weight": body.llm_score_weight,
            "llm_timeout_sec": body.llm_timeout_sec,
            "boundary_adaptation": body.boundary_adaptation,
            "boundary_profile_path": body.boundary_profile_path,
            "adaptive_padding": body.adaptive_padding,
            "half_peak_ratio": body.half_peak_ratio,
            "adaptive_min_before": body.adaptive_min_before,
            "adaptive_max_before": body.adaptive_max_before,
            "adaptive_min_after": body.adaptive_min_after,
            "adaptive_max_after": body.adaptive_max_after,
        },
    )
    if body.source_type == "local" and body.raw_s3_key:
        job.checkpoint_data = {"raw_s3_key": body.raw_s3_key}
    await db.commit()

    # Enqueue for processing
    queue = _get_queue()
    queue.enqueue(str(job.id), priority=user.plan.queue_priority)

    position = queue.get_position(str(job.id))
    return JobStatusResponse(
        job_id=str(job.id),
        status=job.status,
        position=position,
        created_at=job.created_at,
    )


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    user: User = Depends(get_current_user),
    db=Depends(get_async_db),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
):
    jobs, total = await queries.list_user_jobs(db, user.id, page, per_page)

    return JobListResponse(
        jobs=[
            JobStatusResponse(
                job_id=str(j.id),
                status=j.status,
                progress=j.progress,
                current_stage=j.current_stage,
                error=j.error_message if j.status == "failed" else None,
                created_at=j.created_at,
                started_at=j.started_at,
                completed_at=j.completed_at,
            )
            for j in jobs
        ],
        total=total,
        page=page,
        pages=max(1, (total + per_page - 1) // per_page),
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db=Depends(get_async_db),
):
    job = await queries.get_job(db, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(404, "任务不存在")

    clips = []
    if job.status == "completed":
        storage = _get_storage()
        clip_objs, _ = await queries.list_user_clips(db, user.id)
        clips = [
            ClipResponse(
                id=str(c.id),
                job_id=str(c.job_id),
                clip_start=c.clip_start,
                clip_end=c.clip_end,
                duration=c.duration,
                highlight_score=c.highlight_score,
                virality_score=c.virality_score,
                transcript=c.transcript,
                danmaku_count=c.danmaku_count,
                top_keywords=c.top_keywords,
                download_url=storage.presign_download(c.s3_key, expires=3600),
                thumbnail_url=(
                    storage.presign_download(c.thumbnail_s3_key, expires=3600)
                    if c.thumbnail_s3_key else None
                ),
                created_at=c.created_at,
            )
            for c in clip_objs
            if c.job_id == job_id
        ]

    return JobStatusResponse(
        job_id=str(job.id),
        status=job.status,
        progress=job.progress,
        current_stage=job.current_stage,
        clips=clips,
        error=job.error_message if job.status == "failed" else None,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@router.post("/jobs/{job_id}/cleanup-source")
async def cleanup_job_source(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db=Depends(get_async_db),
):
    """
    Cleanup endpoint for source artifacts.

    In full SaaS mode, worker already deletes temporary local source media
    after upload stage; this endpoint is a no-op kept for API parity with lite mode.
    """
    job = await queries.get_job(db, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(404, "任务不存在")
    if job.status in {"queued", "processing", "retrying"}:
        raise HTTPException(409, "任务仍在运行中")
    return {
        "status": "ok",
        "job_id": str(job.id),
        "removed_paths": [],
        "freed_bytes": 0,
        "freed_mb": 0.0,
        "message": "No-op in full mode (temp source files are cleaned by worker).",
    }


# ===================================================================
# Job progress streaming (SSE)
# ===================================================================

@router.get("/jobs/{job_id}/stream")
async def stream_job_progress(
    job_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db=Depends(get_async_db),
):
    job = await queries.get_job(db, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(404, "任务不存在")

    try:
        import redis.asyncio as aioredis
    except ModuleNotFoundError as exc:
        raise HTTPException(503, "SSE 进度流不可用：缺少 redis 依赖") from exc

    redis_client = aioredis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

    async def event_generator():
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(f"job:{job_id}:progress")
        try:
            while True:
                if await request.is_disconnected():
                    break
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message and message["type"] == "message":
                    yield {"data": message["data"].decode()}
                else:
                    await asyncio.sleep(0.5)
        finally:
            await pubsub.unsubscribe(f"job:{job_id}:progress")
            await redis_client.aclose()

    return EventSourceResponse(event_generator())


# ===================================================================
# Clips
# ===================================================================

@router.get("/clips", response_model=ClipListResponse)
async def list_clips(
    user: User = Depends(get_current_user),
    db=Depends(get_async_db),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    sort_by: str = Query(default="created_at"),
):
    allowed_sorts = {"created_at", "virality_score", "highlight_score", "duration"}
    if sort_by not in allowed_sorts:
        sort_by = "created_at"

    clips, total = await queries.list_user_clips(
        db, user.id, page=page, per_page=per_page, sort_by=sort_by
    )
    storage = _get_storage()

    return ClipListResponse(
        clips=[
            ClipResponse(
                id=str(c.id),
                job_id=str(c.job_id),
                clip_start=c.clip_start,
                clip_end=c.clip_end,
                duration=c.duration,
                highlight_score=c.highlight_score,
                virality_score=c.virality_score,
                transcript=c.transcript,
                danmaku_count=c.danmaku_count,
                top_keywords=c.top_keywords,
                download_url=storage.presign_download(c.s3_key, expires=3600),
                thumbnail_url=(
                    storage.presign_download(c.thumbnail_s3_key, expires=3600)
                    if c.thumbnail_s3_key else None
                ),
                created_at=c.created_at,
            )
            for c in clips
        ],
        total=total,
        page=page,
        pages=max(1, (total + per_page - 1) // per_page),
    )


@router.get("/clips/{clip_id}", response_model=ClipResponse)
async def get_clip_detail(
    clip_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db=Depends(get_async_db),
):
    clip = await queries.get_clip(db, clip_id)
    if not clip or clip.user_id != user.id or clip.is_deleted:
        raise HTTPException(404, "片段不存在")

    storage = _get_storage()
    return ClipResponse(
        id=str(clip.id),
        job_id=str(clip.job_id),
        clip_start=clip.clip_start,
        clip_end=clip.clip_end,
        duration=clip.duration,
        highlight_score=clip.highlight_score,
        virality_score=clip.virality_score,
        transcript=clip.transcript,
        danmaku_count=clip.danmaku_count,
        top_keywords=clip.top_keywords,
        download_url=storage.presign_download(clip.s3_key, expires=7200),
        thumbnail_url=(
            storage.presign_download(clip.thumbnail_s3_key, expires=7200)
            if clip.thumbnail_s3_key else None
        ),
        created_at=clip.created_at,
    )


@router.delete("/clips/{clip_id}", status_code=204)
async def delete_clip(
    clip_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db=Depends(get_async_db),
):
    clip = await queries.get_clip(db, clip_id)
    if not clip or clip.user_id != user.id:
        raise HTTPException(404, "片段不存在")

    await queries.soft_delete_clip(db, clip_id)
    await db.commit()

    # Schedule async cleanup of S3 objects
    queue = _get_queue()
    queue.enqueue(f"cleanup:{clip_id}", priority="low")


@router.post("/clips/{clip_id}/adjust")
async def adjust_clip_bounds(
    clip_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db=Depends(get_async_db),
):
    """
    Persist user boundary adjustments and learning signals.

    Full mode stores adjusted metadata; recut is handled by offline jobs.
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

    if new_end <= new_start:
        raise HTTPException(400, "片段边界无效")
    if new_end - new_start < 2.0:
        raise HTTPException(400, "片段时长必须大于等于 2 秒")

    clip = await queries.get_clip(db, clip_id)
    if not clip or clip.user_id != user.id or clip.is_deleted:
        raise HTTPException(404, "片段不存在")

    prev_start = float(clip.clip_start)
    prev_end = float(clip.clip_end)
    clip.clip_start = new_start
    clip.clip_end = new_end
    clip.duration = new_end - new_start
    await db.commit()

    # Learning signal (in full mode we use delta vs previous boundary).
    delta_start = new_start - prev_start
    delta_end = new_end - prev_end
    profile = update_boundary_profile(delta_start, delta_end)

    job = await queries.get_job(db, clip.job_id)
    record = {
        "clip_id": str(clip.id),
        "job_id": str(clip.job_id),
        "user_id": str(user.id),
        "source_type": (job.source_type if job else None),
        "source_url": (job.source_url if job else None),
        "prev_clip_start": prev_start,
        "prev_clip_end": prev_end,
        "new_clip_start": new_start,
        "new_clip_end": new_end,
        "delta_start_vs_prev": delta_start,
        "delta_end_vs_prev": delta_end,
        "adjusted_at": datetime.now(timezone.utc).isoformat(),
        "note": str(payload.get("note", "")).strip() or None,
    }
    log_path = _adjustment_log_path()
    _append_jsonl_record(log_path, record)

    storage = _get_storage()
    return {
        "status": "ok",
        "clip": {
            "id": str(clip.id),
            "job_id": str(clip.job_id),
            "clip_start": clip.clip_start,
            "clip_end": clip.clip_end,
            "duration": clip.duration,
            "highlight_score": clip.highlight_score,
            "score": clip.highlight_score,
            "download_url": storage.presign_download(clip.s3_key, expires=7200),
        },
        "warning": "Full mode only stores adjusted metadata. Re-cut export should be run in background pipeline.",
        "boundary_profile": {
            "count": profile.get("count", 0),
            "mean_start_delta": profile.get("mean_start_delta", 0.0),
            "mean_end_delta": profile.get("mean_end_delta", 0.0),
        },
    }


@router.post("/clips/{clip_id}/feedback", response_model=ClipFeedbackResponse)
async def submit_clip_feedback(
    clip_id: uuid.UUID,
    body: ClipFeedbackRequest,
    user: User = Depends(get_current_user),
    db=Depends(get_async_db),
):
    clip = await queries.get_clip(db, clip_id)
    if not clip or clip.user_id != user.id or clip.is_deleted:
        raise HTTPException(404, "片段不存在")

    record = {
        "clip_id": str(clip.id),
        "job_id": str(clip.job_id),
        "user_id": str(user.id),
        "rating": body.rating,
        "note": body.note.strip() or None,
        "feedback_at": datetime.now(timezone.utc).isoformat(),
        "source_type": None,
        "source_url": None,
        "clip_start": clip.clip_start,
        "clip_end": clip.clip_end,
        "duration": clip.duration,
        "highlight_score": clip.highlight_score,
        "virality_score": clip.virality_score,
        "danmaku_count": clip.danmaku_count,
        "top_keywords": clip.top_keywords or [],
        "adjustments": 0,
        "delta_start_vs_ai": 0.0,
        "delta_end_vs_ai": 0.0,
    }

    job = await queries.get_job(db, clip.job_id)
    if job:
        record["source_type"] = job.source_type
        record["source_url"] = job.source_url

    log_path = _feedback_log_path()
    _append_jsonl_record(log_path, record)

    return ClipFeedbackResponse(
        status="ok",
        clip_id=str(clip.id),
        rating=body.rating,
    )


@router.post("/feedback/retrain")
async def retrain_feedback_ranker(
    request: Request,
    user: User = Depends(get_current_user),
):
    _require_admin_user(user)

    payload: Dict[str, Any] = {}
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    try:
        min_samples = int(payload.get("min_samples", 8))
        l2_alpha = float(payload.get("l2_alpha", 0.2))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "Invalid min_samples or l2_alpha") from exc

    input_path_raw = str(payload.get("input_path", "")).strip()
    output_path_raw = str(payload.get("output_path", "")).strip()
    adjustment_input_path_raw = str(payload.get("adjustment_input_path", "")).strip()
    input_path = _resolve_feedback_artifact_path(
        input_path_raw,
        default_path=_feedback_log_path(),
        label="input_path",
    )
    output_path = _resolve_feedback_artifact_path(
        output_path_raw,
        default_path=default_model_path(),
        label="output_path",
    )
    adjustment_input_path = _resolve_feedback_artifact_path(
        adjustment_input_path_raw,
        default_path=_adjustment_log_path(),
        label="adjustment_input_path",
    )

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


# ===================================================================
# Upload (presigned URL for direct client -> S3 upload)
# ===================================================================

@router.post("/upload/presign", response_model=UploadUrlResponse)
async def get_upload_url(
    user: User = Depends(get_current_user),
):
    storage = _get_storage()
    file_id = uuid.uuid4().hex[:12]
    s3_key = f"raw/{user.id}/{file_id}/source.mp4"
    presigned = storage.presign_upload(s3_key, expires=3600)
    return UploadUrlResponse(
        upload_url=presigned["url"],
        upload_fields=presigned["fields"],
        s3_key=s3_key,
    )


# ===================================================================
# Admin endpoints
# ===================================================================

@router.get("/admin/queue-stats", response_model=QueueStatsResponse)
async def queue_stats(user: User = Depends(get_current_user)):
    _require_admin_user(user)
    queue = _get_queue()
    return QueueStatsResponse(**queue.stats())
