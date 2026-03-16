"""
Train feedback-driven highlight ranker from review logs.

Usage:
  python tools/train_feedback_ranker.py
  python tools/train_feedback_ranker.py --input output/_api_jobs/_feedback/clip_feedback.jsonl --output output/_api_jobs/_feedback/ranker_model.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stream_clipper.ml.feedback_ranker import (
    default_model_path,
    load_jsonl,
    merge_feedback_with_adjustments,
    save_feedback_model,
    train_feedback_model,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Train feedback ranker from clip feedback logs.")
    parser.add_argument(
        "--input",
        default="output/_api_jobs/_feedback/clip_feedback.jsonl",
        help="Input feedback JSONL path",
    )
    parser.add_argument(
        "--output",
        default=str(default_model_path()),
        help="Output model JSON path",
    )
    parser.add_argument(
        "--adjustments",
        default="output/_api_jobs/_feedback/clip_adjustments.jsonl",
        help="Adjustment JSONL path (will be merged into feedback rows)",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=8,
        help="Minimum required feedback samples (default: 8)",
    )
    parser.add_argument(
        "--l2-alpha",
        type=float,
        default=0.2,
        help="Ridge regularization strength (default: 0.2)",
    )
    parser.add_argument("--json", action="store_true", help="Print model JSON")
    args = parser.parse_args()

    rows = load_jsonl(Path(args.input))
    adjustment_rows = load_jsonl(Path(args.adjustments))
    merged_rows = merge_feedback_with_adjustments(rows, adjustment_rows)
    model = train_feedback_model(
        merged_rows,
        min_samples=max(1, int(args.min_samples)),
        l2_alpha=max(0.0, float(args.l2_alpha)),
    )
    out_path = save_feedback_model(model, Path(args.output))

    if args.json:
        print(json.dumps(model, ensure_ascii=False, indent=2))
        return 0

    print("Feedback ranker trained")
    print(f"- Samples: {model['n_samples']}")
    print(f"- Merged rows: {len(merged_rows)}")
    print(f"- Features: {model['feature_keys']}")
    print(f"- Metrics: {model['metrics']}")
    print(f"- Output: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
