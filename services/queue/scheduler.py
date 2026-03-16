"""
Background scheduler that promotes delayed jobs and reclaims stale active jobs.

Run as a standalone process:
    python -m services.queue.scheduler
"""

from __future__ import annotations

import logging
import time

from .job_queue import JobQueue

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

POLL_INTERVAL = 5  # seconds


def run_scheduler(redis_url: str = "redis://localhost:6379/0") -> None:
    queue = JobQueue(redis_url)
    logger.info("Queue scheduler started (poll every %ds)", POLL_INTERVAL)

    while True:
        try:
            promoted = queue.promote_delayed()
            if promoted:
                logger.info("Promoted %d delayed jobs", promoted)
        except Exception:
            logger.exception("Error in scheduler loop")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    import os
    run_scheduler(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
