import shutil
import uuid
from pathlib import Path

from stream_clipper.clipper import ffmpeg_clipper
from stream_clipper.resonance.peaks import Highlight


def test_cut_clips_indexed_preserves_original_indices(monkeypatch) -> None:
    def fake_render(idx, _h, _video_path, output_dir, _safe_title, **_kwargs):
        if idx == 1:
            return idx, None, "failed"
        out_path = output_dir / f"clip_{idx}.mp4"
        out_path.write_bytes(b"ok")
        return idx, out_path, "ok"

    monkeypatch.setattr(ffmpeg_clipper, "_render_one_clip", fake_render)
    monkeypatch.setattr(ffmpeg_clipper, "_workers", lambda total: 1)

    base_tmp = Path(".manual_tmp")
    base_tmp.mkdir(exist_ok=True)
    tmp_path = base_tmp / f"clipper_{uuid.uuid4().hex}"
    tmp_path.mkdir()

    highlights = [
        Highlight(0.0, 10.0, 5.0, 0.5, 10, ["a"]),
        Highlight(10.0, 20.0, 15.0, 0.4, 8, ["b"]),
        Highlight(20.0, 30.0, 25.0, 0.9, 30, ["c"]),
    ]
    try:
        indexed = ffmpeg_clipper.cut_clips_indexed(Path("input.mp4"), highlights, tmp_path, title="demo")

        assert indexed == [
            (0, tmp_path / "clip_0.mp4"),
            (2, tmp_path / "clip_2.mp4"),
        ]
        assert ffmpeg_clipper.cut_clips(Path("input.mp4"), highlights, tmp_path, title="demo") == [
            tmp_path / "clip_0.mp4",
            tmp_path / "clip_2.mp4",
        ]
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
