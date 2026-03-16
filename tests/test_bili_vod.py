import shutil
import uuid
from pathlib import Path

from stream_clipper.ingest import bili_vod


def test_env_cookie_file_includes_bili_session_values(monkeypatch) -> None:
    monkeypatch.setenv("BILI_SESSDATA", "sess-token")
    monkeypatch.setenv("BILI_BILI_JCT", "csrf-token")
    monkeypatch.setenv("BILI_BUVID3", "device-token")

    base_tmp = Path(".manual_tmp")
    base_tmp.mkdir(exist_ok=True)
    tmp_path = base_tmp / f"bili_{uuid.uuid4().hex}"
    tmp_path.mkdir()

    try:
        cookie_file = bili_vod._env_cookie_file(tmp_path)

        assert cookie_file is not None
        text = cookie_file.read_text(encoding="utf-8")
        assert "SESSDATA\tsess-token" in text
        assert "bili_jct\tcsrf-token" in text
        assert "buvid3\tdevice-token" in text
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_auto_cookie_browser_sources_prefers_explicit_value(monkeypatch) -> None:
    monkeypatch.setenv("YTDLP_COOKIES_FROM_BROWSER", "chrome")
    monkeypatch.setenv("YTDLP_AUTO_COOKIES_FROM_BROWSER", "0")

    assert bili_vod._auto_cookie_browser_sources() == ["chrome"]


def test_auto_cookie_browser_sources_can_be_disabled(monkeypatch) -> None:
    monkeypatch.delenv("YTDLP_COOKIES_FROM_BROWSER", raising=False)
    monkeypatch.setenv("YTDLP_AUTO_COOKIES_FROM_BROWSER", "0")

    assert bili_vod._auto_cookie_browser_sources() == []


def test_format_403_error_uses_real_newlines() -> None:
    message = bili_vod._format_403_error("HTTP Error 403: Forbidden")

    assert "\\n" not in message
    assert "HTTP Error 403: Forbidden" in message
