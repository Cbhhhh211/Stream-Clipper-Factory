"""
Ingest a Bilibili live stream.

Runs two concurrent tasks:
  1. Record the stream to a local file via yt-dlp.
  2. Collect danmaku in real-time via WebSocket.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

import httpx
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from ..danmaku.live_collector import BilibiliLiveCollector
from ..logging import console
from ..utils import safe_decode
from .ytdlp_guard import ensure_ytdlp_ready
from .base import IngestResult
from .local import _probe_duration

_BILI_ROOM_API = "https://api.live.bilibili.com/room/v1/Room/get_info"
_MIN_RECORD_BYTES = 256 * 1024
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://live.bilibili.com",
}


def _extract_room_id(url: str) -> Optional[int]:
    m = re.search(r"live\.bilibili\.com/(\d+)", url)
    return int(m.group(1)) if m else None


def _fetch_room_info(room_id: int) -> dict:
    try:
        with httpx.Client(headers=_HEADERS, timeout=10) as client:
            resp = client.get(_BILI_ROOM_API, params={"room_id": room_id})
            data = resp.json()
            if data.get("code") == 0:
                return data.get("data") or {}
    except Exception:
        pass
    return {}


def _fetch_room_title(room_id: int) -> str:
    info = _fetch_room_info(room_id)
    if info:
        return info.get("title", f"live_{room_id}")
    return f"live_{room_id}"


def _start_recording(url: str, output_stem: Path) -> tuple[subprocess.Popen, Path, Path]:
    """
    Start yt-dlp as a background process recording the live stream.

    Uses `%(ext)s` template to avoid invalid extension assumptions on fMP4-like sources.
    """
    ensure_ytdlp_ready()
    stdout_log = output_stem.with_suffix(".yt-dlp.stdout.log")
    stderr_log = output_stem.with_suffix(".yt-dlp.stderr.log")
    output_tmpl = f"{output_stem}.%(ext)s"
    cmd = [
        "yt-dlp",
        "--compat-options",
        "allow-unsafe-ext",
        "--output",
        output_tmpl,
        "--merge-output-format",
        "mp4",
        "--no-part",
        "--hls-use-mpegts",
        "--socket-timeout",
        "30",
        "--retries",
        "5",
        "--fragment-retries",
        "5",
        "--concurrent-fragments",
        "3",
        "--add-header",
        "Referer: https://live.bilibili.com",
        "--add-header",
        (
            "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        url,
    ]
    with stdout_log.open("wb") as out_f, stderr_log.open("wb") as err_f:
        try:
            popen_kwargs = {
                "stdout": out_f,
                "stderr": err_f,
                "stdin": subprocess.PIPE,
            }
            if os.name == "nt":
                # Needed to deliver CTRL_BREAK_EVENT for graceful finalization.
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            process = subprocess.Popen(cmd, **popen_kwargs)
        except FileNotFoundError:
            raise RuntimeError("未找到 yt-dlp，请先安装：pip install yt-dlp") from None
    return process, stdout_log, stderr_log


def _resolve_recorded_output(output_stem: Path) -> Optional[Path]:
    """
    Find the most likely media output produced by yt-dlp.
    """
    candidates = []
    for p in output_stem.parent.glob(f"{output_stem.name}*"):
        if not p.is_file():
            continue
        if p.name.endswith(".yt-dlp.stdout.log") or p.name.endswith(".yt-dlp.stderr.log"):
            continue
        if p.suffix.lower() in {".part", ".ytdl"}:
            continue
        candidates.append(p)

    if not candidates:
        return None

    preferred_exts = {".mp4", ".mkv", ".flv", ".ts", ".webm"}

    def _sort_key(path: Path) -> tuple[int, int]:
        ext_pref = 1 if path.suffix.lower() in preferred_exts else 0
        size = path.stat().st_size if path.exists() else 0
        return ext_pref, size

    return max(candidates, key=_sort_key)


def _graceful_stop_recorder(recorder: subprocess.Popen) -> None:
    """
    Stop yt-dlp gracefully first to ensure output file is finalized.
    """
    if recorder.poll() is not None:
        return

    graceful_stopped = False
    try:
        if os.name == "nt":
            recorder.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            recorder.send_signal(signal.SIGINT)
        recorder.wait(timeout=12)
        graceful_stopped = True
    except Exception:
        graceful_stopped = False

    if not graceful_stopped and recorder.poll() is None:
        recorder.terminate()
        try:
            recorder.wait(timeout=5)
        except subprocess.TimeoutExpired:
            recorder.kill()


class BiliLiveIngest:
    """
    Record a Bilibili live stream and collect danmaku simultaneously.

    Args:
        url: Live room URL (https://live.bilibili.com/<room_id>).
        work_dir: Where to save recording (temp dir if None).
        max_seconds: Auto-stop after this many seconds (0 means wait for Ctrl+C).
    """

    def __init__(
        self,
        url: str,
        work_dir: Optional[str] = None,
        max_seconds: int = 0,
        progress_cb: Optional[Callable[[float, int], None]] = None,
    ):
        self.url = url
        self.work_dir = Path(work_dir) if work_dir else None
        self.max_seconds = max_seconds
        self.progress_cb = progress_cb

    def run(self) -> IngestResult:
        room_id = _extract_room_id(self.url)
        if not room_id:
            raise ValueError(f"无法从链接中提取直播间 ID：{self.url}")

        room_info = _fetch_room_info(room_id)
        title = room_info.get("title", f"live_{room_id}")
        if "live_status" in room_info and int(room_info.get("live_status") or 0) != 1:
            raise RuntimeError(
                f"直播间 {room_id} 当前未开播（live_status={room_info.get('live_status')}）。"
                "请在开播状态下开始录制。"
            )
        console.print(f"[cyan]Live room:[/cyan] {title} (ID: {room_id})")

        if self.work_dir:
            self.work_dir.mkdir(parents=True, exist_ok=True)
            dest_dir = self.work_dir
            is_temp = False
        else:
            dest_dir = Path(tempfile.mkdtemp(prefix="stream_clipper_live_"))
            is_temp = True

        safe_title = re.sub(r"[^\w\-]", "_", title)[:50]
        ts = time.strftime("%Y%m%d_%H%M%S")
        output_stem = dest_dir / f"{safe_title}_{ts}"

        collector = BilibiliLiveCollector(room_id=room_id)
        collector.start()

        recorder, _stdout_log, stderr_log = _start_recording(self.url, output_stem)
        start_time = time.monotonic()

        console.print(
            "[bold green]Recording started.[/bold green] "
            "Press [bold]Ctrl+C[/bold] to stop"
            + (f" (auto-stop in {self.max_seconds}s)" if self.max_seconds else "")
            + "."
        )

        try:
            with Live(console=console, refresh_per_second=2) as live:
                while True:
                    elapsed = time.monotonic() - start_time
                    n_comments = len(collector.get_comments())
                    if self.progress_cb is not None:
                        try:
                            self.progress_cb(elapsed, n_comments)
                        except Exception:
                            pass
                    live.update(
                        Panel(
                            Text.assemble(
                                ("Recording  ", "bold red"),
                                (f"{elapsed:.0f}s elapsed  ", "white"),
                                ("Danmaku: ", "cyan"),
                                (str(n_comments), "bold cyan"),
                            ),
                            title=f"[bold]{title}[/bold]",
                            border_style="green",
                        )
                    )
                    if self.max_seconds and elapsed >= self.max_seconds:
                        console.print(
                            f"\n[yellow]Max duration {self.max_seconds}s reached, stopping...[/yellow]"
                        )
                        break
                    if recorder.poll() is not None:
                        console.print("\n[yellow]Recorder process ended.[/yellow]")
                        break
                    time.sleep(0.5)
        except KeyboardInterrupt:
            console.print("\n[yellow]Ctrl+C received, stopping...[/yellow]")
        finally:
            _graceful_stop_recorder(recorder)
            collector.stop()

        comments = collector.get_comments()
        console.print(
            f"[green]Collected {len(comments)} danmaku comments during recording.[/green]"
        )

        output_path = _resolve_recorded_output(output_stem)
        recorded_bytes = output_path.stat().st_size if output_path and output_path.exists() else 0
        if output_path is None or recorded_bytes < _MIN_RECORD_BYTES:
            stderr_tail = ""
            if stderr_log.exists():
                stderr_tail = safe_decode(stderr_log.read_bytes())[-1200:].strip()
            found_files = [str(p.name) for p in output_stem.parent.glob(f"{output_stem.name}*")]
            raise RuntimeError(
                f"录制文件缺失或体积过小：{output_path or '(none)'}\n"
                f"录制字节数：{recorded_bytes}\n"
                f"匹配到的文件：{found_files}\n"
                "请确认直播已开播，且 yt-dlp 支持该链接。\n"
                f"yt-dlp 错误尾部：\n{stderr_tail or '(empty)'}"
            )

        duration = _probe_duration(output_path)
        console.print(f"[green]Recorded {duration:.0f}s -> {output_path.name}[/green]")

        return IngestResult(
            video_path=output_path,
            comments=comments,
            duration=duration,
            title=f"{title}_{ts}",
            source_url=self.url,
            is_temp=is_temp,
        )
