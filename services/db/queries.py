"""
Reusable database queries for the API and worker layers.

All functions accept a SQLAlchemy session and return model instances or scalars.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from .models import Clip, Job, JobStatus, UsageRecord, User


# ---------------------------------------------------------------------------
# User queries
# ---------------------------------------------------------------------------

async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> Optional[User]:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, email: str, password_hash: str,
                      display_name: str = "") -> User:
    user = User(email=email, password_hash=password_hash, display_name=display_name)
    db.add(user)
    await db.flush()
    return user


# ---------------------------------------------------------------------------
# Job queries
# ---------------------------------------------------------------------------

async def create_job(
    db: AsyncSession,
    user_id: uuid.UUID,
    source_type: str,
    source_url: Optional[str],
    config: dict,
) -> Job:
    job = Job(
        user_id=user_id,
        source_type=source_type,
        source_url=source_url,
        config=config,
    )
    db.add(job)
    await db.flush()
    return job


async def get_job(db: AsyncSession, job_id: uuid.UUID) -> Optional[Job]:
    result = await db.execute(select(Job).where(Job.id == job_id))
    return result.scalar_one_or_none()


async def count_active_jobs(db: AsyncSession, user_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(Job)
        .where(
            Job.user_id == user_id,
            Job.status.in_([JobStatus.QUEUED, JobStatus.PROCESSING, JobStatus.RETRYING]),
        )
    )
    return result.scalar_one()


async def sum_daily_processing_minutes(db: AsyncSession, user_id: uuid.UUID) -> float:
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(func.coalesce(func.sum(UsageRecord.quantity), 0.0))
        .where(
            UsageRecord.user_id == user_id,
            UsageRecord.action == "asr_minutes",
            UsageRecord.recorded_at >= today_start,
        )
    )
    return float(result.scalar_one())


async def list_user_jobs(
    db: AsyncSession, user_id: uuid.UUID, page: int = 1, per_page: int = 20
) -> Tuple[List[Job], int]:
    count_result = await db.execute(
        select(func.count()).select_from(Job).where(Job.user_id == user_id)
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(Job)
        .where(Job.user_id == user_id)
        .order_by(Job.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    jobs = list(result.scalars().all())
    return jobs, total


# Sync variants for workers
def get_job_sync(db: Session, job_id: uuid.UUID) -> Optional[Job]:
    return db.get(Job, job_id)


def update_job_status_sync(db: Session, job_id: uuid.UUID, **kwargs) -> None:
    db.execute(update(Job).where(Job.id == job_id).values(**kwargs))
    db.commit()


# ---------------------------------------------------------------------------
# Clip queries
# ---------------------------------------------------------------------------

async def list_user_clips(
    db: AsyncSession, user_id: uuid.UUID, page: int = 1,
    per_page: int = 20, sort_by: str = "created_at"
) -> Tuple[List[Clip], int]:
    count_result = await db.execute(
        select(func.count())
        .select_from(Clip)
        .where(Clip.user_id == user_id, Clip.is_deleted == False)  # noqa: E712
    )
    total = count_result.scalar_one()

    sort_col = getattr(Clip, sort_by, Clip.created_at)
    result = await db.execute(
        select(Clip)
        .where(Clip.user_id == user_id, Clip.is_deleted == False)  # noqa: E712
        .order_by(sort_col.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    clips = list(result.scalars().all())
    return clips, total


async def get_clip(db: AsyncSession, clip_id: uuid.UUID) -> Optional[Clip]:
    result = await db.execute(select(Clip).where(Clip.id == clip_id))
    return result.scalar_one_or_none()


async def soft_delete_clip(db: AsyncSession, clip_id: uuid.UUID) -> None:
    await db.execute(
        update(Clip).where(Clip.id == clip_id).values(is_deleted=True)
    )


def create_clip_sync(db: Session, **kwargs) -> Clip:
    clip = Clip(**kwargs)
    db.add(clip)
    db.flush()
    return clip


# ---------------------------------------------------------------------------
# Usage queries
# ---------------------------------------------------------------------------

def record_usage_sync(
    db: Session, user_id: uuid.UUID, action: str, quantity: float,
    job_id: Optional[uuid.UUID] = None,
) -> None:
    record = UsageRecord(user_id=user_id, job_id=job_id, action=action, quantity=quantity)
    db.add(record)
    db.flush()
