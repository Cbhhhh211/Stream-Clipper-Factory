"""
Worker entry point.

Run:
    python -m services.worker
"""

import logging
import os

from .processor import ClipWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def main():
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    inference_url = os.getenv("INFERENCE_URL", "http://localhost:8001")

    worker = ClipWorker(redis_url=redis_url, inference_url=inference_url)
    worker.run()


if __name__ == "__main__":
    main()
