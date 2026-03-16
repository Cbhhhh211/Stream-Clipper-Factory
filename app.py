"""
One-click launcher for the new Stream Clipper stack.

Usage:
    python app.py

This starts:
  - Backend API:  http://127.0.0.1:8000
  - Frontend UI:  http://127.0.0.1:5173
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Dict, Optional


ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / "frontend"

API_HOST = os.getenv("APP_API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("APP_API_PORT", "8000"))
WEB_HOST = os.getenv("APP_WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("APP_WEB_PORT", "5173"))
OPEN_BROWSER = os.getenv("APP_OPEN_BROWSER", "1") not in {"0", "false", "False"}
API_RELOAD = os.getenv("APP_API_RELOAD", "0") in {"1", "true", "True"}


def _emit(message: str = "") -> None:
    """Write text to stdout without failing on console encoding issues."""
    encoding = sys.stdout.encoding or "utf-8"
    data = (message + "\n").encode(encoding, errors="replace")
    if hasattr(sys.stdout, "buffer"):
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    else:
        sys.stdout.write(data.decode(encoding, errors="replace"))
        sys.stdout.flush()


def _load_dotenv() -> None:
    """Load environment variables from .env if present."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = v.strip().strip('"').strip("'")


def _stream_output(prefix: str, proc: subprocess.Popen[str]) -> None:
    """Print child process output with a service prefix."""
    if proc.stdout is None:
        return
    for line in proc.stdout:
        _emit(f"[{prefix}] {line.rstrip()}")


def _is_up(url: str, timeout: float = 1.0) -> bool:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False


def _wait_until_up(
    url: str,
    retries: int = 80,
    interval: float = 0.5,
    proc: Optional[subprocess.Popen[str]] = None,
) -> bool:
    for _ in range(retries):
        if proc is not None and proc.poll() is not None:
            return False
        if _is_up(url):
            return True
        time.sleep(interval)
    return False


def _any_up(urls: list[str]) -> bool:
    return any(_is_up(u) for u in urls)


def _start_backend() -> subprocess.Popen[str]:
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "services.api.main:app",
        "--host",
        API_HOST,
        "--port",
        str(API_PORT),
    ]
    if API_RELOAD:
        cmd.append("--reload")
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _start_frontend() -> subprocess.Popen[str]:
    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
    cmd = [npm_cmd, "run", "dev", "--", "--host", WEB_HOST, "--port", str(WEB_PORT)]
    return subprocess.Popen(
        cmd,
        cwd=str(FRONTEND_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _terminate(proc: Optional[subprocess.Popen[str]], name: str) -> None:
    if proc is None:
        return
    if proc.poll() is not None:
        return
    _emit(f"Stopping {name}...")
    proc.terminate()
    try:
        proc.wait(timeout=6)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


def main() -> int:
    _load_dotenv()

    if not FRONTEND_DIR.exists():
        _emit(f"Frontend directory not found: {FRONTEND_DIR}")
        return 1

    api_url = f"http://{API_HOST}:{API_PORT}/health"
    web_url = f"http://{WEB_HOST}:{WEB_PORT}"
    api_probe_urls = [api_url, f"http://localhost:{API_PORT}/health"]
    web_probe_urls = [web_url, f"http://localhost:{WEB_PORT}"]

    _emit("\n" + "=" * 56)
    _emit("Stream Clipper (new stack) starting...")
    _emit(f"Backend health: {api_url}")
    _emit(f"Frontend URL:   {web_url}")
    _emit("=" * 56 + "\n")

    backend = None
    frontend = None
    threads: Dict[str, threading.Thread] = {}
    started_backend = False
    started_frontend = False

    try:
        if _any_up(api_probe_urls):
            _emit("Backend already running, reusing existing service.")
        else:
            backend = _start_backend()
            started_backend = True
            threads["api"] = threading.Thread(
                target=_stream_output, args=("api", backend), daemon=True
            )
            threads["api"].start()
            if not _wait_until_up(api_url, proc=backend):
                _emit("Backend did not become ready in time (or exited early).")
                return 1
            _emit("Backend is ready.")

        if _any_up(web_probe_urls):
            _emit(f"Frontend already running, reusing: {web_url}")
        else:
            frontend = _start_frontend()
            started_frontend = True
            threads["web"] = threading.Thread(
                target=_stream_output, args=("web", frontend), daemon=True
            )
            threads["web"].start()
            if not _wait_until_up(web_url, proc=frontend):
                _emit("Frontend did not become ready in time (or exited early).")
                return 1
            _emit(f"Frontend is ready: {web_url}")

        if OPEN_BROWSER:
            try:
                webbrowser.open(web_url)
            except Exception:
                pass

        if not started_backend and not started_frontend:
            _emit("Both services were already running. Nothing to manage, exiting launcher.")
            return 0

        _emit("Press Ctrl+C to stop services started by this launcher.\n")

        while True:
            if started_backend and backend is not None and backend.poll() is not None:
                _emit("Backend process exited unexpectedly.")
                return 1
            if started_frontend and frontend is not None and frontend.poll() is not None:
                _emit("Frontend process exited unexpectedly.")
                return 1
            time.sleep(0.8)

    except KeyboardInterrupt:
        _emit("\nInterrupted by user.")
        return 0
    finally:
        _terminate(frontend, "frontend")
        _terminate(backend, "backend")
        if started_backend or started_frontend:
            _emit("Services started by launcher have been stopped.")


if __name__ == "__main__":
    raise SystemExit(main())
