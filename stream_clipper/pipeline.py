"""
Shared post-ingest pipeline:
ASR -> resonance scoring -> peak detection -> clip cutting.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
import json
import subprocess
import uuid
from contextlib import contextmanager
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, Generator, List, Optional

from rich.table import Table

from .asr import Segment, transcribe
from .audio_features import compute_rms_energy_per_second
from .clipper import cut_clips
from .config import PipelineConfig
from .ingest.base import IngestResult
from .logging import console
from .ml.llm_reranker import (
    LLMRerankConfig,
    analyze_candidates_with_llm,
)
from .ml.feedback_ranker import (
    extract_features,
    load_feedback_model,
    predict_quality,
)
from .ml.boundary_adaptation import apply_boundary_adaptation, load_boundary_profile
from .resonance import Highlight, compute_scores, find_highlights
from .utils import safe_decode


def _extract_audio(video_path: Path, work_dir: Path) -> Path:
    """Extract mono 16 kHz WAV from source video."""
    audio_path = work_dir / f"audio_16k_{uuid.uuid4().hex[:8]}.wav"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"Audio extraction failed:\n{safe_decode(result.stderr)[-1000:]}")
    return audio_path


@contextmanager
def _managed_audio(video_path: Path, work_dir: Path) -> Generator[Path, None, None]:
    """Extract audio and always clean up temp file."""
    audio_path = _extract_audio(video_path, work_dir)
    try:
        yield audio_path
    finally:
        audio_path.unlink(missing_ok=True)


def _print_highlights_table(highlights: List[Highlight]) -> None:
    table = Table(title="Detected Highlights", show_header=True, header_style="bold magenta")
    table.add_column("#", style="cyan", width=4)
    table.add_column("Start", style="green")
    table.add_column("End", style="green")
    table.add_column("Duration", style="yellow")
    table.add_column("Peak", style="white")
    table.add_column("Score", style="magenta")
    table.add_column("Danmaku", style="blue")
    table.add_column("Top Keywords", style="white")

    for i, h in enumerate(highlights):
        table.add_row(
            str(i + 1),
            f"{h.clip_start:.0f}s",
            f"{h.clip_end:.0f}s",
            f"{h.duration:.0f}s",
            f"{h.peak_time:.0f}s",
            f"{h.score:.3f}",
            str(h.danmaku_count),
            ", ".join(h.top_keywords[:3]) or "-",
        )
    console.print(table)


def _load_feedback_ranker(config: PipelineConfig) -> Optional[dict]:
    if not config.enable_feedback_ranking:
        return None
    model = load_feedback_model(config.feedback_model_path)
    if model:
        console.print(
            f"  Feedback ranker loaded: [white]{model.get('n_samples', 0)}[/white] samples"
        )
    return model


def _score_highlights(
    highlights: List[Highlight],
    ranker_model: Optional[dict],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for idx, h in enumerate(highlights):
        feedback_rank_score: Optional[float] = None
        if ranker_model:
            features = extract_features(
                {
                    "score": h.score,
                    "danmaku_count": h.danmaku_count,
                    "top_keywords": h.top_keywords,
                    "duration": h.duration,
                    "virality_score": None,
                }
            )
            feedback_rank_score = float(predict_quality(features, ranker_model))
        rank_score = float(feedback_rank_score) if feedback_rank_score is not None else float(h.score)
        rows.append(
            {
                "index": idx,
                "clip_start": float(h.clip_start),
                "clip_end": float(h.clip_end),
                "peak_time": float(h.peak_time),
                "score": float(h.score),
                "danmaku_count": int(h.danmaku_count),
                "top_keywords": list(h.top_keywords),
                "feedback_rank_score": feedback_rank_score,
                "llm_score": None,
                "llm_title": None,
                "llm_reason": None,
                "rank_score": rank_score,
            }
        )
    return rows


def _build_comment_index(comments: List[Any]) -> tuple[List[float], List[str]]:
    items: List[tuple[float, str]] = []
    for c in comments:
        text = str(getattr(c, "text", "") or "").strip()
        if not text:
            continue
        items.append((float(getattr(c, "time_offset", 0.0)), text))
    items.sort(key=lambda x: x[0])
    return [x[0] for x in items], [x[1] for x in items]


def _build_segment_index(segments: List[Segment]) -> tuple[List[float], List[tuple[float, float, str]]]:
    items: List[tuple[float, float, str]] = []
    for s in segments:
        text = str(s.text or "").strip()
        if not text:
            continue
        items.append((float(s.start), float(s.end), text))
    items.sort(key=lambda x: x[0])
    return [x[0] for x in items], items


def _excerpt_for_window_indexed(
    clip_start: float,
    clip_end: float,
    comment_times: List[float],
    comment_texts: List[str],
    segment_starts: List[float],
    segment_items: List[tuple[float, float, str]],
) -> tuple[str, str]:
    c_lo = bisect_left(comment_times, clip_start)
    c_hi = bisect_right(comment_times, clip_end)
    danmaku_texts = comment_texts[c_lo:c_hi][:24]

    s_hi = bisect_right(segment_starts, clip_end)
    asr_texts: List[str] = []
    for idx in range(s_hi):
        _s_start, s_end, s_text = segment_items[idx]
        if s_end > clip_start:
            asr_texts.append(s_text)
            if len(asr_texts) >= 14:
                break

    return " | ".join(danmaku_texts), " ".join(asr_texts)


def _apply_llm_rerank(
    rows: List[Dict[str, Any]],
    comments: List[Any],
    segments: List[Segment],
    config: PipelineConfig,
) -> bool:
    llm_cfg = LLMRerankConfig.from_env(
        enabled=config.enable_llm_rerank,
        model=config.llm_model,
        max_candidates=config.llm_max_candidates,
        score_weight=config.llm_score_weight,
        timeout_sec=config.llm_timeout_sec,
    )
    if not llm_cfg.enabled:
        return False

    comment_times, comment_texts = _build_comment_index(comments)
    segment_starts, segment_items = _build_segment_index(segments)

    candidates: List[Dict[str, Any]] = []
    for row in rows:
        danmaku_excerpt, asr_excerpt = _excerpt_for_window_indexed(
            row["clip_start"],
            row["clip_end"],
            comment_times,
            comment_texts,
            segment_starts,
            segment_items,
        )
        candidates.append(
            {
                "index": row["index"],
                "clip_start": row["clip_start"],
                "clip_end": row["clip_end"],
                "duration": max(0.0, row["clip_end"] - row["clip_start"]),
                "score": row["score"],
                "base_rank_score": row["rank_score"],
                "danmaku_count": row["danmaku_count"],
                "top_keywords": row["top_keywords"],
                "danmaku_excerpt": danmaku_excerpt,
                "asr_excerpt": asr_excerpt,
            }
        )

    try:
        llm_scores = rerank_candidates_with_llm(candidates, llm_cfg)
    except Exception as exc:
        console.print(f"[yellow]LLM rerank unavailable, fallback to base ranking: {exc}[/yellow]")
        return False

    if not llm_scores:
        return False

    for row in rows:
        llm = llm_scores.get(int(row["index"]))
        if not llm:
            continue
        llm_score = float(llm.get("score", 0.0))
        row["llm_score"] = llm_score
        row["llm_title"] = llm.get("title")
        row["llm_reason"] = llm.get("reason")
        row["rank_score"] = (
            (1.0 - llm_cfg.score_weight) * float(row["rank_score"])
            + llm_cfg.score_weight * llm_score
        )
    return True


def _semantic_config_from_pipeline(config: PipelineConfig) -> LLMRerankConfig:
    return LLMRerankConfig.from_env(
        enabled=config.enable_semantic_enrichment,
        model=config.semantic_model or config.llm_model,
        max_candidates=config.semantic_max_candidates,
        score_weight=config.semantic_score_weight,
        timeout_sec=config.semantic_timeout_sec,
    )


def _build_llm_candidates(
    rows: List[Dict[str, Any]],
    comments: List[Any],
    segments: List[Segment],
) -> List[Dict[str, Any]]:
    comment_times, comment_texts = _build_comment_index(comments)
    segment_starts, segment_items = _build_segment_index(segments)

    candidates: List[Dict[str, Any]] = []
    for row in rows:
        danmaku_excerpt, asr_excerpt = _excerpt_for_window_indexed(
            row["clip_start"],
            row["clip_end"],
            comment_times,
            comment_texts,
            segment_starts,
            segment_items,
        )
        candidates.append(
            {
                "index": row["index"],
                "clip_start": row["clip_start"],
                "clip_end": row["clip_end"],
                "duration": max(0.0, row["clip_end"] - row["clip_start"]),
                "score": row["score"],
                "base_rank_score": row["rank_score"],
                "danmaku_count": row["danmaku_count"],
                "top_keywords": row["top_keywords"],
                "danmaku_excerpt": danmaku_excerpt,
                "asr_excerpt": asr_excerpt,
            }
        )
    return candidates


def _apply_llm_candidate_analysis(
    rows: List[Dict[str, Any]],
    comments: List[Any],
    segments: List[Segment],
    config: PipelineConfig,
) -> tuple[bool, bool]:
    llm_cfg = LLMRerankConfig.from_env(
        enabled=config.enable_llm_rerank,
        model=config.llm_model,
        max_candidates=config.llm_max_candidates,
        score_weight=config.llm_score_weight,
        timeout_sec=config.llm_timeout_sec,
    )
    semantic_cfg = _semantic_config_from_pipeline(config)

    if not llm_cfg.enabled and not semantic_cfg.enabled:
        return False, False

    analysis_cfg = LLMRerankConfig.from_env(
        enabled=True,
        model=llm_cfg.model or semantic_cfg.model,
        max_candidates=max(
            llm_cfg.max_candidates if llm_cfg.enabled else 0,
            semantic_cfg.max_candidates if semantic_cfg.enabled else 0,
        ),
        score_weight=llm_cfg.score_weight if llm_cfg.enabled else semantic_cfg.score_weight,
        timeout_sec=max(
            llm_cfg.timeout_sec if llm_cfg.enabled else 0.0,
            semantic_cfg.timeout_sec if semantic_cfg.enabled else 0.0,
        ),
    )

    candidates = _build_llm_candidates(rows, comments, segments)
    try:
        analyses = analyze_candidates_with_llm(candidates, analysis_cfg)
    except Exception as exc:
        console.print(f"[yellow]LLM candidate analysis unavailable, fallback to base ranking: {exc}[/yellow]")
        return False, False

    if not analyses:
        return False, False

    semantic_applied = False
    llm_applied = False
    for row in rows:
        analysis = analyses.get(int(row["index"]))
        if not analysis:
            continue

        semantic_score = float(analysis.get("score", 0.0))
        row["semantic_score"] = semantic_score
        row["content_summary"] = str(
            analysis.get("summary")
            or analysis.get("title")
            or row.get("content_summary")
            or ""
        ).strip()[:240]
        row["content_tags"] = list(analysis.get("tags", []) or [])[:6]
        row["content_hook"] = bool(analysis.get("hook", False))
        semantic_applied = True

        if llm_cfg.enabled:
            row["llm_score"] = semantic_score
            row["llm_title"] = analysis.get("title")
            row["llm_reason"] = analysis.get("reason")
            row["rank_score"] = (
                (1.0 - llm_cfg.score_weight) * float(row["rank_score"])
                + llm_cfg.score_weight * semantic_score
            )
            llm_applied = True
        elif semantic_cfg.enabled:
            row["rank_score"] = (
                (1.0 - semantic_cfg.score_weight) * float(row["rank_score"])
                + semantic_cfg.score_weight * semantic_score
            )

    return llm_applied, semantic_applied


def run_pipeline(
    ingest_result: IngestResult,
    output_dir: str,
    config: Optional[PipelineConfig] = None,
) -> List[Path]:
    """Run full local pipeline for one ingest result."""
    if config is None:
        config = PipelineConfig()

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    work_dir = output_path / "_work"
    work_dir.mkdir(exist_ok=True)

    video_path = ingest_result.video_path
    comments = ingest_result.comments
    duration = ingest_result.duration
    title = ingest_result.title

    console.print("\n[bold cyan]Pipeline start[/bold cyan]")
    console.print(f"  Video    : [white]{video_path.name}[/white]")
    console.print(f"  Duration : [white]{duration:.0f}s ({duration / 60:.1f} min)[/white]")
    console.print(f"  Danmaku  : [white]{len(comments)} comments[/white]")

    clip_paths: List[Path] = []
    ranking_source = "resonance"
    ranked_rows: List[Dict[str, Any]] = []
    boundary_profile = None
    llm_applied = False
    semantic_applied = False
    timings_sec: Dict[str, float] = {}

    try:
        console.print("\n[bold yellow]Step 1/3  Transcribing audio[/bold yellow]")
        t_asr = perf_counter()
        audio_energy = None
        with _managed_audio(video_path, work_dir) as audio_path:
            segments: List[Segment] = transcribe(
                str(audio_path),
                model_size=config.model_size,
                language=config.language,
            )
            try:
                audio_energy = compute_rms_energy_per_second(audio_path)
            except Exception as exc:
                console.print(f"[yellow]Audio energy extraction skipped: {exc}[/yellow]")
        timings_sec["asr_and_audio_features"] = round(perf_counter() - t_asr, 3)

        console.print("\n[bold yellow]Step 2/3  Computing resonance scores[/bold yellow]")
        t_scoring = perf_counter()
        times, scores = compute_scores(
            comments,
            segments,
            duration,
            window=config.window,
            weights=config.weights,
            audio_energy=audio_energy,
        )
        console.print(
            f"  Score range: [white]{scores.min():.3f} - {scores.max():.3f}[/white] "
            f"mean=[white]{scores.mean():.3f}[/white]"
        )

        if config.save_scores:
            score_json = work_dir / "scores.json"
            score_json.write_text(
                json.dumps(
                    {
                        "times": times.tolist(),
                        "scores": scores.tolist(),
                        "n_comments": len(comments),
                        "n_segments": len(segments),
                        "duration": duration,
                        "title": title,
                        "weights": list(config.weights),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            console.print(f"  Scores saved -> [dim]{score_json}[/dim]")

        ranker_model = _load_feedback_ranker(config)
        candidate_top_n = config.top_n
        if ranker_model or config.enable_llm_rerank:
            candidate_top_n = max(config.top_n, config.top_n * config.candidate_multiplier)

        highlights_all = find_highlights(
            times,
            scores,
            comments,
            top_n=candidate_top_n,
            pad_before=config.pad_before,
            pad_after=config.pad_after,
            min_gap=config.min_gap,
            threshold=config.threshold,
            video_duration=duration,
            adaptive_padding=config.adaptive_padding,
            half_peak_ratio=config.half_peak_ratio,
            adaptive_min_before=config.adaptive_min_before,
            adaptive_max_before=config.adaptive_max_before,
            adaptive_min_after=config.adaptive_min_after,
            adaptive_max_after=config.adaptive_max_after,
        )

        if not highlights_all:
            console.print(
                "[red]No highlights found.[/red] "
                "Try --threshold 0 or verify danmaku/speech availability."
            )
            return []

        ranked_rows = _score_highlights(highlights_all, ranker_model)
        llm_applied, semantic_applied = _apply_llm_candidate_analysis(
            ranked_rows,
            comments,
            segments,
            config,
        )
        timings_sec["scoring_and_ranking"] = round(perf_counter() - t_scoring, 3)

        ranked_rows = sorted(ranked_rows, key=lambda r: float(r["rank_score"]), reverse=True)[: config.top_n]
        ranked_rows = sorted(ranked_rows, key=lambda r: float(r["clip_start"]))
        ai_bounds = [(float(r["clip_start"]), float(r["clip_end"])) for r in ranked_rows]

        if llm_applied and ranker_model:
            ranking_source = "llm+feedback_model"
        elif llm_applied:
            ranking_source = "llm+resonance"
        elif semantic_applied and ranker_model:
            ranking_source = "semantic+feedback_model"
        elif semantic_applied:
            ranking_source = "semantic+resonance"
        elif ranker_model:
            ranking_source = "feedback_model"
        else:
            ranking_source = "resonance"

        if config.enable_boundary_adaptation:
            boundary_profile = load_boundary_profile(config.boundary_profile_path)
            for row in ranked_rows:
                ns, ne = apply_boundary_adaptation(
                    float(row["clip_start"]),
                    float(row["clip_end"]),
                    video_duration=duration,
                    profile=boundary_profile,
                    min_duration=5.0,
                )
                row["clip_start"] = ns
                row["clip_end"] = ne

        highlights = [
            Highlight(
                clip_start=float(r["clip_start"]),
                clip_end=float(r["clip_end"]),
                peak_time=float(r["peak_time"]),
                score=float(r["score"]),
                danmaku_count=int(r["danmaku_count"]),
                top_keywords=list(r["top_keywords"]),
            )
            for r in ranked_rows
        ]

        console.print(f"\n  Found [bold green]{len(highlights)}[/bold green] highlights.")
        _print_highlights_table(highlights)

        console.print(f"\n[bold yellow]Step 3/3  Cutting {len(highlights)} clips[/bold yellow]")
        t_clipping = perf_counter()
        clip_paths = cut_clips(
            video_path,
            highlights,
            output_path,
            title=title,
            reencode_threshold=config.reencode_threshold,
        )
        timings_sec["clip_encoding"] = round(perf_counter() - t_clipping, 3)

        summary = {
            "title": title,
            "source": str(ingest_result.source_url or video_path),
            "duration": duration,
            "n_danmaku": len(comments),
            "n_segments": len(segments),
            "timings_sec": timings_sec,
            "ranking_source": ranking_source,
            "llm_rerank_applied": bool(llm_applied),
            "semantic_enrichment_applied": bool(semantic_applied),
            "boundary_adaptation": (
                {
                    "enabled": bool(config.enable_boundary_adaptation),
                    "count": int((boundary_profile or {}).get("count", 0)),
                    "mean_start_delta": float((boundary_profile or {}).get("mean_start_delta", 0.0)),
                    "mean_end_delta": float((boundary_profile or {}).get("mean_end_delta", 0.0)),
                }
                if boundary_profile is not None
                else {"enabled": False}
            ),
            "highlights": [
                {
                    "rank": i + 1,
                    "ai_clip_start": ai_bounds[i][0] if i < len(ai_bounds) else h.clip_start,
                    "ai_clip_end": ai_bounds[i][1] if i < len(ai_bounds) else h.clip_end,
                    "clip_start": h.clip_start,
                    "clip_end": h.clip_end,
                    "peak_time": h.peak_time,
                    "score": h.score,
                    "rank_score": (
                        float(ranked_rows[i]["rank_score"])
                        if i < len(ranked_rows)
                        else h.score
                    ),
                    "feedback_rank_score": (
                        ranked_rows[i].get("feedback_rank_score")
                        if i < len(ranked_rows)
                        else None
                    ),
                    "llm_score": (
                        ranked_rows[i].get("llm_score")
                        if i < len(ranked_rows)
                        else None
                    ),
                    "llm_title": (
                        ranked_rows[i].get("llm_title")
                        if i < len(ranked_rows)
                        else None
                    ),
                    "llm_reason": (
                        ranked_rows[i].get("llm_reason")
                        if i < len(ranked_rows)
                        else None
                    ),
                    "semantic_score": (
                        ranked_rows[i].get("semantic_score")
                        if i < len(ranked_rows)
                        else None
                    ),
                    "content_summary": (
                        ranked_rows[i].get("content_summary")
                        if i < len(ranked_rows)
                        else None
                    ),
                    "content_tags": (
                        ranked_rows[i].get("content_tags")
                        if i < len(ranked_rows)
                        else []
                    ),
                    "content_hook": (
                        ranked_rows[i].get("content_hook")
                        if i < len(ranked_rows)
                        else False
                    ),
                    "danmaku_count": h.danmaku_count,
                    "top_keywords": h.top_keywords,
                    "file": str(clip_paths[i].name) if i < len(clip_paths) else None,
                }
                for i, h in enumerate(highlights)
            ],
        }

        summary_path = output_path / "summary.json"
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        console.print(f"\n[bold green]Done! {len(clip_paths)} clips saved -> {output_path}[/bold green]")
        if timings_sec:
            console.print(
                "  Timings: "
                + ", ".join(f"{k}={v:.2f}s" for k, v in timings_sec.items())
            )
        console.print(f"Summary: [dim]{summary_path}[/dim]")

    finally:
        if ingest_result.is_temp and video_path.exists():
            video_path.unlink(missing_ok=True)
            console.print(f"[dim]Cleaned up temp video: {video_path.name}[/dim]")

    return clip_paths
