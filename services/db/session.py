"""
Database session management.

Provides both async (for API) and sync (for workers) session factories.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncGenerator, Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://clipper:clipper@localhost:5432/stream_clipper"
)
DATABASE_URL_ASYNC = DATABASE_URL.replace(
    "postgresql://", "postgresql+asyncpg://"
)

# --- Sync engine (workers) ---

_sync_engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)
SyncSessionLocal = sessionmaker(bind=_sync_engine, expire_on_commit=False)

# --- Async engine (API) ---

_async_engine = create_async_engine(
    DATABASE_URL_ASYNC,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)
AsyncSessionLocal = async_sessionmaker(
    bind=_async_engine, class_=AsyncSession, expire_on_commit=False
)


# --- Dependency helpers ---

async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async session, auto-closes."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@contextmanager
def get_sync_db() -> Generator[Session, None, None]:
    """Worker helper: yields a sync session, auto-closes."""
    session = SyncSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def create_tables() -> None:
    """Create all tables (for dev/testing). Use Alembic in production."""
    Base.metadata.create_all(bind=_sync_engine)
