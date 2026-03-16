"""
Evaluate clip quality from user feedback logs.

Usage:
  python tools/evaluate_feedback.py
  python tools/evaluate_feedback.py --input output/_api_jobs/_feedback/clip_feedback.jsonl --json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List


def rating_to_numeric(rating: str) -> float:
    r = (rating or "").strip().lower()
    if r == "good":
        return 1.0
    if r == "average":
        return 0.5
    if r == "bad":
        return 0.0
    return 0.0


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw:
                continue
            try:
                rows.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return rows


def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    rating_counts = Counter((str(r.get("rating", "")).lower() for r in rows))
    feedback_scores = [rating_to_numeric(str(r.get("rating", ""))) for r in rows]
    avg_feedback = mean(feedback_scores) if feedback_scores else 0.0

    by_rating_scores: Dict[str, List[float]] = defaultdict(list)
    keyword_counter: Counter[str] = Counter()
    score_bins: Dict[str, List[float]] = defaultdict(list)

    for r in rows:
        rating = str(r.get("rating", "")).lower()
        hs = r.get("highlight_score", r.get("score"))
        if isinstance(hs, (int, float)):
            by_rating_scores[rating].append(float(hs))
            score_bin = min(9, max(0, int(float(hs) * 10)))
            score_bins[f"{score_bin/10:.1f}-{(score_bin+1)/10:.1f}"].append(
                rating_to_numeric(rating)
            )
        if rating == "good":
            for kw in r.get("top_keywords", []) or []:
                if isinstance(kw, str) and kw.strip():
                    keyword_counter[kw.strip()] += 1

    avg_score_by_rating = {
        k: round(mean(v), 4) for k, v in by_rating_scores.items() if v
    }
    calibration = {
        b: round(mean(v), 4) for b, v in sorted(score_bins.items()) if v
    }

    return {
        "total_feedback": len(rows),
        "rating_counts": dict(rating_counts),
        "avg_feedback_score": round(avg_feedback, 4),
        "avg_highlight_score_by_rating": avg_score_by_rating,
        "score_bin_feedback_calibration": calibration,
        "top_keywords_in_good_clips": keyword_counter.most_common(20),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate clip quality from feedback logs.")
    parser.add_argument(
        "--input",
        default="output/_api_jobs/_feedback/clip_feedback.jsonl",
        help="Path to feedback JSONL file",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    args = parser.parse_args()

    path = Path(args.input)
    rows = load_jsonl(path)
    summary = summarize(rows)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    print("Feedback Evaluation")
    print(f"- Input: {path}")
    print(f"- Total feedback: {summary['total_feedback']}")
    print(f"- Rating counts: {summary['rating_counts']}")
    print(f"- Avg feedback score (good=1, average=0.5, bad=0): {summary['avg_feedback_score']}")
    print(f"- Avg highlight score by rating: {summary['avg_highlight_score_by_rating']}")
    print(f"- Score calibration (bin -> avg feedback): {summary['score_bin_feedback_calibration']}")
    print("- Top keywords in good clips:")
    for kw, count in summary["top_keywords_in_good_clips"]:
        print(f"  - {kw}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
