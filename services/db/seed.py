"""Seed script to insert default plan rows."""

from .models import Plan
from .session import SyncSessionLocal


def seed_plans() -> None:
    db = SyncSessionLocal()
    try:
        existing = db.query(Plan).count()
        if existing > 0:
            return

        plans = [
            Plan(
                name="free",
                max_concurrent_jobs=1,
                daily_minutes_limit=30,
                max_clip_storage_mb=500,
                clip_retention_days=7,
                queue_priority="low",
                viral_ranking_enabled=False,
            ),
            Plan(
                name="pro",
                max_concurrent_jobs=3,
                daily_minutes_limit=120,
                max_clip_storage_mb=5000,
                clip_retention_days=30,
                queue_priority="normal",
                viral_ranking_enabled=True,
            ),
            Plan(
                name="enterprise",
                max_concurrent_jobs=10,
                daily_minutes_limit=9999,
                max_clip_storage_mb=50000,
                clip_retention_days=None,
                queue_priority="high",
                viral_ranking_enabled=True,
            ),
        ]
        db.add_all(plans)
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    from .session import create_tables
    create_tables()
    seed_plans()
    print("Database seeded.")
