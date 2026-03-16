import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services.api import routes


def test_get_storage_reuses_singleton(monkeypatch) -> None:
    created = []

    class FakeStorage:
        def __init__(self):
            created.append(object())

    monkeypatch.setattr("services.storage.s3.S3Storage", FakeStorage)
    monkeypatch.setattr(routes, "_STORAGE_SINGLETON", None)

    first = routes._get_storage()
    second = routes._get_storage()

    assert first is second
    assert len(created) == 1


def test_require_admin_user_uses_email_allowlist(monkeypatch) -> None:
    monkeypatch.setenv("FEEDBACK_RETRAIN_ADMIN_EMAILS", "admin@example.com")
    routes._require_admin_user(SimpleNamespace(email="admin@example.com"))

    with pytest.raises(HTTPException):
        routes._require_admin_user(SimpleNamespace(email="user@example.com"))


def test_resolve_feedback_artifact_path_rejects_escape(monkeypatch) -> None:
    base_tmp = Path(".manual_tmp")
    base_tmp.mkdir(exist_ok=True)
    tmp_path = base_tmp / f"routes_{uuid.uuid4().hex}"
    tmp_path.mkdir()
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    allowed = routes._feedback_artifact_root() / "clip_feedback.jsonl"

    try:
        resolved = routes._resolve_feedback_artifact_path(
            "",
            default_path=allowed,
            label="input_path",
        )
        assert resolved == allowed

        with pytest.raises(HTTPException):
            routes._resolve_feedback_artifact_path(
                str(tmp_path.parent / "outside.jsonl"),
                default_path=allowed,
                label="input_path",
            )
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_append_jsonl_record_writes_complete_line() -> None:
    base_tmp = Path(".manual_tmp")
    base_tmp.mkdir(exist_ok=True)
    tmp_path = base_tmp / f"jsonl_{uuid.uuid4().hex}"
    tmp_path.mkdir()
    log_path = tmp_path / "events.jsonl"
    try:
        routes._append_jsonl_record(log_path, {"a": 1})
        routes._append_jsonl_record(log_path, {"b": 2})

        assert log_path.read_text(encoding="utf-8").splitlines() == [
            '{"a": 1}',
            '{"b": 2}',
        ]
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
