"""
Redis-based job queue with priority lanes, delayed retry, and dead-letter.

Queue topology:
  jobs:priority:high     <- paid tier (enterprise)
  jobs:priority:normal   <- pro tier
  jobs:priority:low      <- free tier
  jobs:delayed           <- sorted set (score = execute_at unix timestamp)
  jobs:dead_letter       <- permanently failed jobs
  jobs:active:{worker}   <- currently processing (visibility timeout)
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import redis

logger = logging.getLogger(__name__)

PRIORITY_QUEUES = [
    "jobs:priority:high",
    "jobs:priority:normal",
    "jobs:priority:low",
]

# Visibility timeout: if a worker dies, the job becomes re-claimable after this
VISIBILITY_TIMEOUT_SEC = 30 * 60  # 30 minutes

# Retry backoff schedule (seconds)
RETRY_BACKOFF = [30, 120, 600]


class JobQueue:
    """Redis-backed priority job queue with retry and dead-letter support."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.r = redis.from_url(redis_url, decode_responses=True)

    # --- Enqueue ---

    def enqueue(self, job_id: str, priority: str = "normal", delay: int = 0) -> None:
        """
        Add a job to the queue.

        Args:
            job_id:   UUID string of the job.
            priority: "high", "normal", or "low".
            delay:    Seconds to delay before the job becomes available.
        """
        payload = json.dumps({
            "job_id": job_id,
            "enqueued_at": datetime.now(timezone.utc).isoformat(),
            "priority": priority,
        })

        if delay > 0:
            execute_at = time.time() + delay
            self.r.zadd("jobs:delayed", {payload: execute_at})
            logger.info("Job %s delayed by %ds", job_id, delay)
        else:
            queue_name = f"jobs:priority:{priority}"
            self.r.lpush(queue_name, payload)
            logger.info("Job %s enqueued to %s", job_id, queue_name)

    # --- Dequeue ---

    def dequeue(self, worker_id: str, timeout: int = 5) -> Optional[dict]:
        """
        Blocking dequeue respecting priority order.

        Moves the job into an active-tracking key with a visibility timeout
        so that if the worker crashes, the job can be reclaimed.
        """
        result = self.r.brpop(PRIORITY_QUEUES, timeout=timeout)
        if result is None:
            return None

        _queue, raw = result
        payload = json.loads(raw)

        # Track in active set with TTL
        active_key = f"jobs:active:{worker_id}"
        self.r.setex(active_key, VISIBILITY_TIMEOUT_SEC, raw)

        logger.info("Worker %s claimed job %s", worker_id, payload["job_id"])
        return payload

    # --- Lifecycle ---

    def complete(self, worker_id: str) -> None:
        """Mark current job done — remove from active tracking."""
        self.r.delete(f"jobs:active:{worker_id}")

    def fail(self, worker_id: str) -> None:
        """Remove from active tracking without completing."""
        self.r.delete(f"jobs:active:{worker_id}")

    # --- Retry ---

    def schedule_retry(self, job_id: str, retry_count: int,
                       priority: str = "normal") -> int:
        """
        Schedule a retry with exponential backoff.

        Returns the delay in seconds.
        """
        delay = RETRY_BACKOFF[min(retry_count - 1, len(RETRY_BACKOFF) - 1)]
        self.enqueue(job_id, priority=priority, delay=delay)
        logger.info("Job %s scheduled for retry #%d in %ds", job_id, retry_count, delay)
        return delay

    # --- Dead letter ---

    def dead_letter(self, job_id: str, error: str) -> None:
        """Move a permanently failed job to the dead-letter queue."""
        self.r.lpush("jobs:dead_letter", json.dumps({
            "job_id": job_id,
            "error": error,
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }))
        logger.warning("Job %s moved to dead letter: %s", job_id, error[:200])

    # --- Delayed job promoter ---

    def promote_delayed(self) -> int:
        """
        Move delayed jobs whose scheduled time has passed into their
        priority queue. Should be called periodically (every ~5s).

        Returns the number of promoted jobs.
        """
        now = time.time()
        ready = self.r.zrangebyscore("jobs:delayed", "-inf", now)
        promoted = 0

        for raw in ready:
            removed = self.r.zrem("jobs:delayed", raw)
            if removed:
                payload = json.loads(raw)
                priority = payload.get("priority", "normal")
                queue_name = f"jobs:priority:{priority}"
                self.r.lpush(queue_name, raw)
                promoted += 1
                logger.info("Promoted delayed job %s to %s", payload["job_id"], queue_name)

        return promoted

    # --- Progress pub/sub ---

    def publish_progress(self, job_id: str, stage: str, progress: float) -> None:
        """Publish progress update via Redis pub/sub for SSE streaming."""
        self.r.publish(f"job:{job_id}:progress", json.dumps({
            "stage": stage,
            "progress": round(progress, 3),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))

    # --- Queue position ---

    def get_position(self, job_id: str) -> Optional[int]:
        """Approximate queue position across all priority lanes."""
        position = 0
        for queue_name in PRIORITY_QUEUES:
            items = self.r.lrange(queue_name, 0, -1)
            for i, raw in enumerate(items):
                payload = json.loads(raw)
                if payload["job_id"] == job_id:
                    return position + len(items) - i
            position += len(items)
        return None

    # --- Stats ---

    def stats(self) -> dict:
        return {
            "high": self.r.llen("jobs:priority:high"),
            "normal": self.r.llen("jobs:priority:normal"),
            "low": self.r.llen("jobs:priority:low"),
            "delayed": self.r.zcard("jobs:delayed"),
            "dead_letter": self.r.llen("jobs:dead_letter"),
        }
