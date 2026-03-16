"""
Real-time danmaku collector for Bilibili live streams via WebSocket.

Bilibili live danmaku WebSocket protocol:
  - URL: wss://broadcastlv.chat.bilibili.com/sub
  - Binary frame format: 16-byte header + payload
    Header: total_len(4B) header_len(2B) proto_ver(2B) op(4B) seq_id(4B)
  - Operations: 2=HEARTBEAT, 3=HEARTBEAT_REPLY, 5=SEND_MSG_REPLY, 7=AUTH, 8=AUTH_REPLY
  - Protocol versions: 0/1=raw JSON, 2=zlib-compressed
"""

import asyncio
import json
import struct
import time
import threading
import zlib
from typing import List, Optional

import websockets

from .models import DanmakuComment
from ..logging import console


_WS_URL = "wss://broadcastlv.chat.bilibili.com/sub"
_HEADER_FMT = ">IHHII"  # total_len, header_len, proto_ver, op, seq_id
_HEADER_LEN = struct.calcsize(_HEADER_FMT)  # == 16


def _pack(data: dict, op: int, seq: int = 1) -> bytes:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    header = struct.pack(_HEADER_FMT, _HEADER_LEN + len(body), _HEADER_LEN, 1, op, seq)
    return header + body


def _unpack_frames(data: bytes) -> List[dict]:
    """Recursively unpack one or more frames from a binary blob."""
    results: List[dict] = []
    offset = 0
    while offset < len(data):
        if offset + _HEADER_LEN > len(data):
            break
        total_len, header_len, proto_ver, op, _ = struct.unpack_from(_HEADER_FMT, data, offset)
        body = data[offset + header_len : offset + total_len]
        offset += total_len

        if op == 5:  # SEND_MSG_REPLY
            if proto_ver == 2:
                try:
                    body = zlib.decompress(body)
                    results.extend(_unpack_frames(body))
                except zlib.error:
                    pass
            else:
                try:
                    results.append(json.loads(body.decode("utf-8")))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass
    return results


class BilibiliLiveCollector:
    """
    Collect danmaku from a Bilibili live room in a background thread.

    Thread-safety: ``_comments`` is guarded by ``_lock``; all mutations
    happen on the async thread, all reads happen via ``get_comments()``.

    Usage::

        collector = BilibiliLiveCollector(room_id=12345)
        collector.start()
        # ... do other work ...
        collector.stop()
        comments = collector.get_comments()
    """

    def __init__(self, room_id: int):
        self.room_id = room_id
        self._comments: List[DanmakuComment] = []
        self._lock = threading.Lock()
        self._running = False
        self._start_time: float = 0.0
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._error: Optional[Exception] = None  # surfaced from background thread

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._running = True
        self._error = None
        self._start_time = time.monotonic()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)

    def get_comments(self) -> List[DanmakuComment]:
        with self._lock:
            return list(self._comments)

    def raise_if_error(self) -> None:
        """Re-raise any unhandled error from the background thread."""
        if self._error is not None:
            raise self._error

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._capture())
        except Exception as exc:
            # Surface non-cancellation errors so callers can inspect them
            self._error = exc
            console.print(f"[red]LiveCollector error: {exc}[/red]")
        finally:
            self._loop.close()

    async def _capture(self) -> None:
        auth_payload = {
            "uid": 0,
            "roomid": self.room_id,
            "protover": 2,
            "platform": "web",
            "clientver": "1.14.3",
            "type": 2,
        }
        auth_packet = _pack(auth_payload, op=7)
        heartbeat_packet = _pack({}, op=2)

        while self._running:
            try:
                async with websockets.connect(_WS_URL, ping_interval=None) as ws:
                    await ws.send(auth_packet)

                    async def _heartbeat() -> None:
                        while self._running:
                            await asyncio.sleep(30)
                            try:
                                await ws.send(heartbeat_packet)
                            except Exception:
                                break

                    hb_task = asyncio.create_task(_heartbeat())
                    try:
                        while self._running:
                            try:
                                raw = await asyncio.wait_for(ws.recv(), timeout=60)
                            except asyncio.TimeoutError:
                                continue
                            if not isinstance(raw, bytes):
                                continue
                            for msg in _unpack_frames(raw):
                                self._handle_message(msg)
                    finally:
                        hb_task.cancel()
            except Exception:
                if self._running:
                    await asyncio.sleep(3)  # reconnect after brief pause

    def _handle_message(self, msg: dict) -> None:
        cmd = msg.get("cmd", "")
        if cmd == "DANMU_MSG":
            info = msg.get("info", [])
            if len(info) >= 2:
                text = str(info[1])
                user_id = (
                    str(info[2][0])
                    if len(info) > 2 and isinstance(info[2], list)
                    else ""
                )
                elapsed = time.monotonic() - self._start_time
                comment = DanmakuComment(
                    time_offset=elapsed,
                    text=text,
                    user_id=user_id,
                    dtype=1,
                )
                with self._lock:
                    self._comments.append(comment)
