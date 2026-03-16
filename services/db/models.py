"""
SQLAlchemy ORM models for the Stream Clipper SaaS platform.

Tables: users, api_keys, jobs, clips, usage_records, plans
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Plans (reference table)
# ---------------------------------------------------------------------------

class Plan(Base):
    __tablename__ = "plans"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    max_concurrent_jobs: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    daily_minutes_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    max_clip_storage_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    clip_retention_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    queue_priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    viral_ranking_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    def __repr__(self) -> str:
        return f"<Plan {self.name}>"


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(128))
    plan_name: Mapped[str] = mapped_column(
        String(32), ForeignKey("plans.name"), nullable=False, default="free"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    plan: Mapped[Plan] = relationship("Plan", lazy="joined")
    api_keys: Mapped[List["ApiKey"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    jobs: Mapped[List["Job"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    clips: Mapped[List["Clip"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User {self.email}>"


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------

class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    key_hash: Mapped[str] = mapped_column(String(256), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    scopes: Mapped[Optional[list]] = mapped_column(
        JSONB, default=lambda: ["jobs:write", "clips:read"]
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    user: Mapped[User] = relationship(back_populates="api_keys")


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

class JobStatus:
    QUEUED = "queued"
    PROCESSING = "processing"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    ALL = (QUEUED, PROCESSING, RETRYING, COMPLETED, FAILED, CANCELLED)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=JobStatus.QUEUED, index=True
    )
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(Text)
    config: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)

    # Progress
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    current_stage: Mapped[Optional[str]] = mapped_column(String(32))
    worker_id: Mapped[Optional[str]] = mapped_column(String(128))

    # Checkpoint for resume-on-retry
    checkpoint_stage: Mapped[Optional[str]] = mapped_column(String(32))
    checkpoint_data: Mapped[Optional[dict]] = mapped_column(JSONB)

    # Retry
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Storage references
    raw_video_s3_key: Mapped[Optional[str]] = mapped_column(String(512))
    audio_s3_key: Mapped[Optional[str]] = mapped_column(String(512))

    # Metadata
    video_duration: Mapped[Optional[float]] = mapped_column(Float)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    user: Mapped[User] = relationship(back_populates="jobs")
    clips: Mapped[List["Clip"]] = relationship(back_populates="job", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Job {self.id} [{self.status}]>"


# ---------------------------------------------------------------------------
# Clips
# ---------------------------------------------------------------------------

class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # Storage
    s3_key: Mapped[str] = mapped_column(String(512), nullable=False)
    thumbnail_s3_key: Mapped[Optional[str]] = mapped_column(String(512))
    file_size_bytes: Mapped[Optional[int]] = mapped_column(Integer)

    # Clip metadata
    clip_start: Mapped[float] = mapped_column(Float, nullable=False)
    clip_end: Mapped[float] = mapped_column(Float, nullable=False)
    duration: Mapped[float] = mapped_column(Float, nullable=False)

    # Scores
    highlight_score: Mapped[Optional[float]] = mapped_column(Float)
    virality_score: Mapped[Optional[float]] = mapped_column(Float)
    predicted_ctr: Mapped[Optional[float]] = mapped_column(Float)
    predicted_share: Mapped[Optional[float]] = mapped_column(Float)

    # Content snapshot
    transcript: Mapped[Optional[str]] = mapped_column(Text)
    danmaku_count: Mapped[Optional[int]] = mapped_column(Integer)
    top_keywords: Mapped[Optional[list]] = mapped_column(JSONB)

    # Lifecycle
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    job: Mapped[Job] = relationship(back_populates="clips")
    user: Mapped[User] = relationship(back_populates="clips")

    def to_response(self) -> dict:
        """Serialize for API response."""
        return {
            "id": str(self.id),
            "job_id": str(self.job_id),
            "clip_start": self.clip_start,
            "clip_end": self.clip_end,
            "duration": self.duration,
            "highlight_score": self.highlight_score,
            "virality_score": self.virality_score,
            "transcript": self.transcript,
            "danmaku_count": self.danmaku_count,
            "top_keywords": self.top_keywords,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<Clip {self.id} [{self.clip_start:.0f}s-{self.clip_end:.0f}s]>"


# ---------------------------------------------------------------------------
# Usage tracking
# ---------------------------------------------------------------------------

class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    job_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id")
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
