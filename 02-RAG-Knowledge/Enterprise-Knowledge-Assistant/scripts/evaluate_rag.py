"""Offline RAG evaluation CLI (items 14+15).

Runs the full RAG pipeline over data/eval/golden_dataset.jsonl, judges
faithfulness via the configured LLM provider (no Ragas), writes the
machine-readable report (evaluation/results.json + results.csv), and applies
the quality gates from data/eval/quality_gates.yaml. Exit code 1 when a gate
fails — CI-ready.

Usage:
    .venv\\Scripts\\python.exe scripts\\evaluate_rag.py                 # full run
    .venv\\Scripts\\python.exe scripts\\evaluate_rag.py --limit 5      # quick smoke
    .venv\\Scripts\\python.exe scripts\\evaluate_rag.py --skip-judge   # mechanical only
    .venv\\Scripts\\python.exe scripts\\evaluate_rag.py --category unsupported
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Windows consoles default to cp932/cp1252 and crash on non-ASCII print output
# (project gotcha from Phase 8); force UTF-8 with replacement so a summary
# containing document names with odd characters never kills the CLI.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

from app.evaluation.quality_gates import check_quality_gates, load_thresholds, print_summary, write_report
from app.evaluation.runner import load_dataset, run_evaluation

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = PROJECT_ROOT / "evaluation"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="evaluate only the first N rows")
    parser.add_argument("--category", type=str, default=None, help="evaluate one category only")
    parser.add_argument("--skip-judge", action="store_true", help="skip the LLM faithfulness judge")
    parser.add_argument("--dataset", type=Path, default=None, help="alternate dataset path")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="report output directory")
    args = parser.parse_args()

    rows = load_dataset(args.dataset)
    if args.category:
        rows = [r for r in rows if r["category"] == args.category]
        if not rows:
            print(f"no rows in category {args.category!r}")
            return 2
    if args.limit:
        rows = rows[: args.limit]

    print(f"Evaluating {len(rows)} questions (judge={'on' if not args.skip_judge else 'OFF'})…")
    started = time.perf_counter()

    def progress(msg: str) -> None:
        print(f"  … {msg}")

    results = run_evaluation(
        rows,
        judge=not args.skip_judge,
        progress=progress,
    )
    gate_report = check_quality_gates(results, load_thresholds())
    elapsed = time.perf_counter() - started
    paths = write_report(results, args.out, gate_report)

    print_summary(gate_report, results)
    print(f"\nReport: {paths['json']}")
    print(f"        {paths['csv']}")
    print(f"Wall clock: {elapsed:.0f}s")
    return 0 if gate_report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())