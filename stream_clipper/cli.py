"""
Stream Clipper CLI

Three subcommands:
  clip-local  – Process a local video file (+ optional danmaku XML)
  clip-bili   – Download a Bilibili VOD and process it
  clip-live   – Capture a Bilibili live stream and process it
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Tuple

from .config import PipelineConfig
from .logging import console


# ──────────────────────────────────────────────────────────────────────────────
# Shared argument helpers
# ──────────────────────────────────────────────────────────────────────────────

def _add_pipeline_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--output", "-o", default=os.getenv("OUTPUT_DIR", "./output"),
        help="Output directory for clips (default: ./output)",
    )
    p.add_argument(
        "--model", "-m", default=os.getenv("WHISPER_MODEL", "base"),
        metavar="SIZE",
        help="Whisper model size: tiny/base/small/medium/large-v2/large-v3 (default: base)",
    )
    p.add_argument(
        "--language", default="zh",
        help="Language code for ASR, e.g. 'zh' / 'en' / 'auto' (default: zh)",
    )
    p.add_argument(
        "--top-n", "-n", type=int, default=int(os.getenv("TOP_N", "10")),
        help="Number of top highlights to extract (default: 10)",
    )
    p.add_argument(
        "--pad-before", type=float, default=15.0,
        help="Seconds to include before each peak (default: 15)",
    )
    p.add_argument(
        "--pad-after", type=float, default=30.0,
        help="Seconds to include after each peak (default: 30)",
    )
    p.add_argument(
        "--min-gap", type=float, default=60.0,
        help="Minimum seconds between adjacent peaks (default: 60)",
    )
    p.add_argument(
        "--threshold", type=float, default=None,
        help="Score threshold for peaks (default: auto = mean + 1σ)",
    )
    p.add_argument(
        "--window", type=float, default=10.0,
        help="Sliding window size in seconds for resonance scoring (default: 10)",
    )
    p.add_argument(
        "--weights", type=str, default="0.4,0.4,0.2",
        metavar="W1,W2,W3",
        help="Comma-separated weights for density, excitement, overlap (default: 0.4,0.4,0.2)",
    )


def _parse_weights(s: str) -> Tuple[float, float, float]:
    parts = [float(x) for x in s.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("--weights must be three comma-separated floats")
    return (parts[0], parts[1], parts[2])


def _build_config(args: argparse.Namespace) -> PipelineConfig:
    return PipelineConfig(
        model_size=args.model,
        language=None if args.language == "auto" else args.language,
        top_n=args.top_n,
        pad_before=args.pad_before,
        pad_after=args.pad_after,
        min_gap=args.min_gap,
        threshold=args.threshold,
        window=args.window,
        weights=_parse_weights(args.weights),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Subcommand handlers
# ──────────────────────────────────────────────────────────────────────────────

def cmd_local(args: argparse.Namespace) -> None:
    from .ingest.local import LocalIngest
    from .pipeline import run_pipeline

    console.print(f"[bold cyan]Mode:[/bold cyan] Local file  →  {args.video}")
    ingest = LocalIngest(video_path=args.video, danmaku_path=args.danmaku)
    result = ingest.run()
    run_pipeline(result, output_dir=args.output, config=_build_config(args))


def cmd_bili(args: argparse.Namespace) -> None:
    from .ingest.bili_vod import BiliVodIngest
    from .pipeline import run_pipeline

    console.print(f"[bold cyan]Mode:[/bold cyan] Bilibili VOD  →  {args.url}")
    work_dir = Path(args.output) / "_download"
    ingest = BiliVodIngest(
        url=args.url,
        work_dir=str(work_dir),
        cookies_file=args.cookies,
        sessdata=os.getenv("BILI_SESSDATA"),
    )
    result = ingest.run()
    run_pipeline(result, output_dir=args.output, config=_build_config(args))


def cmd_live(args: argparse.Namespace) -> None:
    from .ingest.bili_live import BiliLiveIngest
    from .pipeline import run_pipeline

    console.print(f"[bold cyan]Mode:[/bold cyan] Bilibili Live  →  {args.url}")
    work_dir = Path(args.output) / "_recording"
    ingest = BiliLiveIngest(
        url=args.url,
        work_dir=str(work_dir),
        max_seconds=args.duration,
    )
    result = ingest.run()
    run_pipeline(result, output_dir=args.output, config=_build_config(args))


# ──────────────────────────────────────────────────────────────────────────────
# Argument parser
# ──────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stream-clipper",
        description=(
            "Automatic highlight clipper using danmaku–subtitle resonance.\n"
            "Finds moments where viewer comments and speech content spike together."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── clip-local ──
    p_local = sub.add_parser(
        "clip-local",
        help="Process a local video file with an optional danmaku XML.",
        description="Highlight clips from a local video + danmaku file.",
    )
    p_local.add_argument("video", help="Path to video file (MP4, MKV, FLV, …)")
    p_local.add_argument(
        "--danmaku", "-d", default=None,
        help="Path to Bilibili XML danmaku file (optional)",
    )
    _add_pipeline_args(p_local)
    p_local.set_defaults(func=cmd_local)

    # ── clip-bili ──
    p_bili = sub.add_parser(
        "clip-bili",
        help="Download a Bilibili VOD and generate highlight clips.",
        description=(
            "Downloads the video via yt-dlp and the danmaku XML via Bilibili API,\n"
            "then runs the resonance pipeline."
        ),
    )
    p_bili.add_argument("url", help="Bilibili video URL (https://www.bilibili.com/video/BV…)")
    p_bili.add_argument(
        "--cookies", default=None,
        help="Path to Netscape cookies.txt for members-only content",
    )
    _add_pipeline_args(p_bili)
    p_bili.set_defaults(func=cmd_bili)

    # ── clip-live ──
    p_live = sub.add_parser(
        "clip-live",
        help="Record a Bilibili live stream and generate highlight clips.",
        description=(
            "Records the live stream (yt-dlp) and collects danmaku (WebSocket)\n"
            "simultaneously. Press Ctrl+C or use --duration to stop."
        ),
    )
    p_live.add_argument("url", help="Bilibili live room URL (https://live.bilibili.com/<id>)")
    p_live.add_argument(
        "--duration", type=int, default=0,
        help="Auto-stop recording after N seconds (default: 0 = until Ctrl+C)",
    )
    _add_pipeline_args(p_live)
    p_live.set_defaults(func=cmd_live)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
