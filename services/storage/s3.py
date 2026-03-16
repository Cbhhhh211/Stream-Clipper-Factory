"""
Object storage abstraction over S3-compatible backends (AWS S3, MinIO).

Bucket layout:
  raw/{user_id}/{job_id}/source.mp4        # original video (24h TTL)
  danmaku/{user_id}/{job_id}/comments.json # parsed danmaku
  asr/{user_id}/{job_id}/segments.json     # ASR transcript
  clips/{user_id}/{job_id}/000.mp4         # final clips
  thumbnails/{user_id}/{job_id}/000.jpg    # clip thumbnails
  temp/{job_id}/audio.wav                  # intermediate (6h TTL)
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class S3Storage:
    """S3/MinIO object storage client."""

    def __init__(
        self,
        bucket: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        region: Optional[str] = None,
    ):
        self.bucket = bucket or os.getenv("S3_BUCKET", "stream-clipper")
        endpoint = endpoint_url or os.getenv("S3_ENDPOINT_URL", "http://localhost:9000")
        region = region or os.getenv("S3_REGION", "us-east-1")

        self.s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=region,
            aws_access_key_id=os.getenv("S3_ACCESS_KEY", "minioadmin"),
            aws_secret_access_key=os.getenv("S3_SECRET_KEY", "minioadmin"),
            config=BotoConfig(
                retries={"max_attempts": 3, "mode": "adaptive"},
                max_pool_connections=50,
                signature_version="s3v4",
            ),
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        """Create bucket if it does not exist (for local MinIO dev)."""
        try:
            self.s3.head_bucket(Bucket=self.bucket)
        except ClientError:
            try:
                self.s3.create_bucket(Bucket=self.bucket)
                logger.info("Created bucket: %s", self.bucket)
            except ClientError:
                logger.warning("Could not create bucket %s — may already exist", self.bucket)

    # --- Upload ---

    def upload_file(self, local_path: str, s3_key: str,
                    content_type: Optional[str] = None) -> None:
        """Upload a local file to S3."""
        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type

        self.s3.upload_file(local_path, self.bucket, s3_key, ExtraArgs=extra_args or None)
        logger.info("Uploaded %s -> s3://%s/%s", local_path, self.bucket, s3_key)

    def upload_json(self, data: Any, s3_key: str) -> None:
        """Serialize data to JSON and upload."""
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.s3.put_object(
            Bucket=self.bucket, Key=s3_key, Body=body,
            ContentType="application/json",
        )
        logger.info("Uploaded JSON -> s3://%s/%s (%d bytes)", self.bucket, s3_key, len(body))

    # --- Download ---

    def download_file(self, s3_key: str, local_path: str) -> str:
        """Download an S3 object to a local file path."""
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        self.s3.download_file(self.bucket, s3_key, local_path)
        logger.info("Downloaded s3://%s/%s -> %s", self.bucket, s3_key, local_path)
        return local_path

    def download_temp(self, s3_key: str, suffix: str = "") -> str:
        """Download to a temp file. Returns the temp file path."""
        ext = suffix or Path(s3_key).suffix
        fd, temp_path = tempfile.mkstemp(suffix=ext)
        os.close(fd)
        self.download_file(s3_key, temp_path)
        return temp_path

    def download_json(self, s3_key: str) -> Any:
        """Download and parse a JSON file from S3."""
        response = self.s3.get_object(Bucket=self.bucket, Key=s3_key)
        body = response["Body"].read().decode("utf-8")
        return json.loads(body)

    # --- Presigned URLs ---

    def presign_download(self, s3_key: str, expires: int = 3600) -> str:
        """Generate a presigned URL for downloading."""
        url = self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": s3_key},
            ExpiresIn=expires,
        )
        return url

    def presign_upload(self, s3_key: str, expires: int = 3600,
                       content_type: str = "video/mp4") -> dict:
        """Generate a presigned POST for direct client upload."""
        conditions = [
            {"Content-Type": content_type},
            ["content-length-range", 1, 10 * 1024 * 1024 * 1024],  # up to 10 GB
        ]
        fields = {"Content-Type": content_type}
        response = self.s3.generate_presigned_post(
            Bucket=self.bucket, Key=s3_key,
            Fields=fields, Conditions=conditions,
            ExpiresIn=expires,
        )
        return response

    # --- Delete ---

    def delete(self, s3_key: str) -> None:
        """Delete an object from S3."""
        self.s3.delete_object(Bucket=self.bucket, Key=s3_key)
        logger.info("Deleted s3://%s/%s", self.bucket, s3_key)

    def delete_prefix(self, prefix: str) -> int:
        """Delete all objects under a prefix. Returns count of deleted objects."""
        paginator = self.s3.get_paginator("list_objects_v2")
        deleted = 0
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            objects = page.get("Contents", [])
            if not objects:
                continue
            delete_keys = [{"Key": obj["Key"]} for obj in objects]
            self.s3.delete_objects(
                Bucket=self.bucket, Delete={"Objects": delete_keys}
            )
            deleted += len(delete_keys)

        logger.info("Deleted %d objects under prefix %s", deleted, prefix)
        return deleted

    # --- Utility ---

    def exists(self, s3_key: str) -> bool:
        """Check if an object exists."""
        try:
            self.s3.head_object(Bucket=self.bucket, Key=s3_key)
            return True
        except ClientError:
            return False

    def get_size(self, s3_key: str) -> int:
        """Get object size in bytes."""
        response = self.s3.head_object(Bucket=self.bucket, Key=s3_key)
        return response["ContentLength"]
