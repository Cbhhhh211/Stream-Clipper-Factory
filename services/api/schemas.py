"""
Pydantic request/response schemas for the API.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

class JobCreate(BaseModel):
    source_type: str = Field(description="'local', 'bili_vod', 'bili_live', 'web_vod', or 'web_live'")
    source_url: Optional[str] = None
    raw_s3_key: Optional[str] = None
    top_n: int = Field(default=10, ge=1, le=50)
    clip_duration: float = Field(default=45.0, ge=5.0, le=3600.0)
    min_clip_duration: float = Field(default=15.0, ge=5.0, le=3600.0)
    max_clip_duration: float = Field(default=60.0, ge=10.0, le=3600.0)
    duration: int = Field(default=1800, ge=30, le=43200)
    viral_rank: bool = False
    candidate_multiplier: int = Field(default=3, ge=1, le=10)
    feedback_rank: bool = True
    feedback_model_path: Optional[str] = Field(default=None, max_length=512)
    llm_rerank: Optional[bool] = None
    llm_model: Optional[str] = Field(default=None, max_length=128)
    llm_max_candidates: int = Field(default=20, ge=1, le=100)
    llm_score_weight: float = Field(default=0.65, ge=0.0, le=1.0)
    llm_timeout_sec: float = Field(default=30.0, ge=1.0, le=180.0)
    boundary_adaptation: bool = True
    boundary_profile_path: Optional[str] = Field(default=None, max_length=512)
    adaptive_padding: bool = True
    half_peak_ratio: float = Field(default=0.5, ge=0.05, le=0.95)
    adaptive_min_before: float = Field(default=5.0, ge=0.0, le=120.0)
    adaptive_max_before: Optional[float] = Field(default=None, ge=0.0, le=3600.0)
    adaptive_min_after: float = Field(default=8.0, ge=0.0, le=120.0)
    adaptive_max_after: Optional[float] = Field(default=None, ge=0.0, le=3600.0)


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: float = 0.0
    current_stage: Optional[str] = None
    position: Optional[int] = None
    clips: List[ClipResponse] = Field(default_factory=list)
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class JobListResponse(BaseModel):
    jobs: List[JobStatusResponse]
    total: int
    page: int
    pages: int


# ---------------------------------------------------------------------------
# Clips
# ---------------------------------------------------------------------------

class ClipResponse(BaseModel):
    id: str
    job_id: str
    clip_start: float
    clip_end: float
    duration: float
    highlight_score: Optional[float] = None
    virality_score: Optional[float] = None
    transcript: Optional[str] = None
    danmaku_count: Optional[int] = None
    top_keywords: Optional[List[str]] = None
    download_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    created_at: Optional[datetime] = None


class ClipListResponse(BaseModel):
    clips: List[ClipResponse]
    total: int
    page: int
    pages: int


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

class UploadUrlResponse(BaseModel):
    upload_url: str
    upload_fields: dict
    s3_key: str


# ---------------------------------------------------------------------------
# Queue stats (admin)
# ---------------------------------------------------------------------------

class QueueStatsResponse(BaseModel):
    high: int
    normal: int
    low: int
    delayed: int
    dead_letter: int


# ---------------------------------------------------------------------------
# Clip feedback
# ---------------------------------------------------------------------------

class ClipFeedbackRequest(BaseModel):
    rating: Literal["good", "average", "bad"]
    note: str = Field(default="", max_length=500)


class ClipFeedbackResponse(BaseModel):
    status: str
    clip_id: str
    rating: Literal["good", "average", "bad"]
