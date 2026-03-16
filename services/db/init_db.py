"""
Database initialization script.

Creates all tables and seeds default plan data.

Run:
    python -m services.db.init_db
"""

from __future__ import annotations

import logging

from .models import Base
from .session import _sync_engine, SyncSessionLocal
from .seed import seed_plans

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init_db() -> None:
    """Create all tables and seed data."""
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=_sync_engine)
    logger.info("Tables created.")

    logger.info("Seeding plans...")
    seed_plans()
    logger.info("Database initialization complete.")


if __name__ == "__main__":
    init_db()
