import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

from services.worker import processor


class _Energy:
    def tolist(self):
        return [0.1, 0.2]


def test_stage_asr_cleans_local_and_s3_audio(monkeypatch) -> None:
    base_tmp = Path(".manual_tmp")
    base_tmp.mkdir(exist_ok=True)
    tmp_path = base_tmp / f"asr_{uuid.uuid4().hex}"
    tmp_path.mkdir()
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"wav")

    uploaded = []
    deleted = []
    uploaded_json = []

    class FakeStorage:
        def upload_file(self, local_path, s3_key, content_type=None):
            uploaded.append((local_path, s3_key, content_type))

        def delete(self, s3_key):
            deleted.append(s3_key)

        def upload_json(self, data, s3_key):
            uploaded_json.append((data, s3_key))

    class FakeInference:
        def transcribe(self, s3_key):
            assert s3_key == "temp/job-1/audio.wav"
            return [{"start": 0.0, "end": 1.0, "text": "hello"}]

    worker = processor.ClipWorker.__new__(processor.ClipWorker)
    worker.storage = FakeStorage()
    worker.inference = FakeInference()

    monkeypatch.setattr(worker, "_extract_audio", lambda _video_path: str(audio_path))
    monkeypatch.setattr(processor, "compute_rms_energy_per_second", lambda _path: _Energy())
    monkeypatch.setattr(processor, "record_usage_sync", lambda *args, **kwargs: None)

    job = SimpleNamespace(id="job-1", user_id="user-1", audio_s3_key=None)
    context = {"local_video_path": "video.mp4", "duration": 120.0}

    try:
        out = worker._stage_asr(job, {}, context, db=None)

        assert uploaded == [(str(audio_path), "temp/job-1/audio.wav", "audio/wav")]
        assert deleted == ["temp/job-1/audio.wav"]
        assert not audio_path.exists()
        assert job.audio_s3_key is None
        assert out["segment_count"] == 1
        assert uploaded_json[0][1] == "asr/user-1/job-1/segments.json"
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_stage_danmaku_falls_back_to_helper_functions(monkeypatch) -> None:
    uploaded = []

    class FakeStorage:
        def upload_json(self, data, s3_key):
            uploaded.append((data, s3_key))

    class FakeIngest:
        def __init__(self, url, sessdata=None):
            self.url = url
            self.sessdata = sessdata

    class FakeComment:
        def __init__(self, time_offset, text, user_id, dtype):
            self.time_offset = time_offset
            self.text = text
            self.user_id = user_id
            self.dtype = dtype

    worker = processor.ClipWorker.__new__(processor.ClipWorker)
    worker.storage = FakeStorage()

    monkeypatch.setattr("stream_clipper.ingest.bili_vod.BiliVodIngest", FakeIngest)
    monkeypatch.setattr("stream_clipper.ingest.bili_vod._extract_bvid", lambda _url: "BV1demo")
    monkeypatch.setattr(
        "stream_clipper.ingest.bili_vod._fetch_video_info",
        lambda _bvid, _cookies=None: {"cid": 123, "title": "demo"},
    )

    def fake_download(cid, dest_dir, title):
        xml_path = Path(dest_dir) / f"{title}.xml"
        xml_path.write_text("<i />", encoding="utf-8")
        assert cid == 123
        return xml_path

    monkeypatch.setattr("stream_clipper.ingest.bili_vod._download_danmaku", fake_download)
    monkeypatch.setattr(
        "stream_clipper.danmaku.parser.parse_xml",
        lambda _path: [FakeComment(1.5, "test", "u1", 1)],
    )

    temp_root = Path(".manual_tmp")
    temp_root.mkdir(exist_ok=True)
    temp_dir = temp_root / f"danmaku_{uuid.uuid4().hex}"
    temp_dir.mkdir()

    class _TempDir:
        def __enter__(self):
            return str(temp_dir)

        def __exit__(self, exc_type, exc, tb):
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False

    monkeypatch.setattr(processor.tempfile, "TemporaryDirectory", lambda prefix=None: _TempDir())

    job = SimpleNamespace(
        source_type="bili_vod",
        source_url="https://www.bilibili.com/video/BV1demo",
        user_id="user-1",
        id="job-1",
    )
    out = worker._stage_danmaku(job, {}, {}, db=None)

    assert out["danmaku_count"] == 1
    assert uploaded == [
        (
            [{"time_offset": 1.5, "text": "test", "user_id": "u1", "dtype": 1}],
            "danmaku/user-1/job-1/comments.json",
        )
    ]


def test_cleanup_context_artifacts_removes_remaining_temp_files() -> None:
    base_tmp = Path(".manual_tmp")
    base_tmp.mkdir(exist_ok=True)
    tmp_path = base_tmp / f"cleanup_{uuid.uuid4().hex}"
    tmp_path.mkdir()
    clip_dir = tmp_path / "clips"
    clip_dir.mkdir()
    clip_path = clip_dir / "clip.mp4"
    clip_path.write_bytes(b"clip")
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"video")

    worker = processor.ClipWorker.__new__(processor.ClipWorker)
    try:
        worker._cleanup_context_artifacts(
            {
                "clip_files": [{"local_path": str(clip_path)}],
                "clip_temp_dir": str(clip_dir),
                "local_video_path": str(video_path),
            },
            include_video=True,
        )

        assert not clip_path.exists()
        assert not clip_dir.exists()
        assert not video_path.exists()
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
