"""
Phase 1 — regression gate.

Diffs a snapshot's aggregate metrics against the stored baseline
(eval/BASELINE.json) and emits a verdict:

  🟢 PASS   every watched metric dropped by ≤ 0.05 (or improved)
  🟡 WARN   worst drop between 0.05 and 0.15 (regressed question ids listed)
  🔴 FAIL   worst drop > 0.15 — CI should exit non-zero

Latency metrics (mean/p95 ms) are judged on relative slowdown instead:
> +25% counts as a regression step on the latency axis.

Higher-is-better metrics: recall_*, *_coverage, refusal_accuracy.
Lower-is-better metrics:  first_relevant_rank, mean_total_ms, p95_total_ms.

Phase 2: snapshots may carry an optional "ragas" block (LLM-judged metrics).
Those are reported as informational delta rows under the diff's `ragas` key
but NEVER influence the gate verdict - the regression gate stays LLM-free
and deterministic by design.

CLI (for future CI):
  python -m eval.gate <snapshot_id>              # diff vs BASELINE.json
  python -m eval.gate <snapshot_id> --against <other_snapshot_id>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from eval import metrics
from eval.runner import get_baseline, load_snapshot

# metric -> (direction, per-step regression threshold, fail threshold)
WATCHED = {
    "recall_at_k":        ("higher", 0.05, 0.15),
    "citation_coverage":  ("higher", 0.05, 0.15),
    "must_term_coverage": ("higher", 0.05, 0.15),
    "refusal_accuracy":   ("higher", 0.05, 0.15),
    "first_relevant_rank": ("lower", 0.50, 1.50),   # rank steps, not fractions
}
LATENCY_KEYS = ("mean_total_ms", "p95_total_ms")
LATENCY_SLOWDOWN_WARN = 0.25   # +25% latency = warn step
LATENCY_SLOWDOWN_FAIL = 0.60   # +60% latency = fail step


def _direction(metric: str) -> str:
    return WATCHED.get(metric, ("higher", 0.05, 0.15))[0] if metric in WATCHED else "higher"


def diff_snapshots(current: Dict[str, Any], baseline: Dict[str, Any]) -> Dict[str, Any]:
    """
    Metric-by-metric diff of two snapshot dicts (full snapshots or the short
    baseline record — both carry an `aggregate` dict).
    """
    cur_agg = current.get("aggregate", {})
    base_agg = baseline.get("aggregate", {})
    all_keys = list(metrics.AGG_METRICS)

    metric_rows: List[Dict[str, Any]] = []
    worst_drop = 0.0
    worst_metric = None

    for key in all_keys:
        cur, base = cur_agg.get(key), base_agg.get(key)
        if cur is None or base is None:
            metric_rows.append({"metric": key, "baseline": base, "current": cur,
                                "delta": None, "verdict": None, "note": "missing"})
            continue
        direction = _direction(key)
        delta = round(cur - base, 4)
        # normalized change: positive = better
        change = delta if direction == "higher" else -delta
        if key in LATENCY_KEYS:
            rel = (cur / base - 1.0) if base else 0.0
            step = "regress" if rel > LATENCY_SLOWDOWN_FAIL else \
                   "warn" if rel > LATENCY_SLOWDOWN_WARN else \
                   "improve" if rel < -0.05 else "ok"
            note = f"{rel:+.0%} latency"
        else:
            if change >= 0:
                step = "improve" if change > 0.001 else "ok"
            else:
                thr_warn = WATCHED.get(key, ("higher", 0.05, 0.15))[1]
                thr_fail = WATCHED.get(key, ("higher", 0.05, 0.15))[2]
                step = "regress" if -change > thr_fail else "warn" if -change > thr_warn else "ok"
            note = ""
        metric_rows.append({
            "metric": key, "baseline": base, "current": cur,
            "delta": delta, "change": change, "verdict": step, "note": note,
        })
        # worst *quality* drop decides the overall verdict (latency excluded)
        if key not in LATENCY_KEYS and change < 0 and -change > worst_drop:
            worst_drop = -change
            worst_metric = key

    latency_regress = any(r["verdict"] == "regress" for r in metric_rows if r["metric"] in LATENCY_KEYS)
    quality_regress = any(r["verdict"] == "regress" for r in metric_rows if r["metric"] not in LATENCY_KEYS)
    quality_warn = any(r["verdict"] == "warn" for r in metric_rows if r["metric"] not in LATENCY_KEYS)
    latency_warn = any(r["verdict"] == "warn" for r in metric_rows if r["metric"] in LATENCY_KEYS)

    if quality_regress or (latency_regress and not quality_warn):
        icon, status = "🔴", "FAIL"
    elif quality_warn or latency_warn:
        icon, status = "🟡", "WARN"
    else:
        icon, status = "🟢", "PASS"

    # questions that got worse between the two runs (by recall, then rank)
    regressed_ids = _regressed_questions(current, baseline)

    out = {
        "verdict": status,
        "icon": icon,
        "worst_metric": worst_metric,
        "worst_drop": round(worst_drop, 4),
        "regressed_ids": regressed_ids,
        "metrics": metric_rows,
        "baseline_id": baseline.get("snapshot_id"),
        "current_id": current.get("snapshot_id"),
    }

    # Phase 2: informational ragas rows — deltas only, never part of the gate
    # verdict (the cheap deterministic gate stays LLM-free by design).
    ragas_rows = _ragas_rows(current, baseline)
    if ragas_rows:
        out["ragas"] = ragas_rows
    return out


def _ragas_rows(current: Dict[str, Any], baseline: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Per-metric ragas delta rows for snapshots that carry a ragas block."""
    cur, base = current.get("ragas"), baseline.get("ragas")
    if not isinstance(cur, dict) or cur.get("error"):
        return []
    cur_agg = cur.get("aggregate") or {}
    base_agg = (base or {}).get("aggregate") or {} if isinstance(base, dict) else {}
    rows = []
    for m in cur.get("metrics") or list(cur_agg.keys()):
        c, b = cur_agg.get(m), base_agg.get(m)
        rows.append({
            "metric": f"ragas.{m}",
            "baseline": b,
            "current": c,
            "delta": (round(c - b, 4) if isinstance(c, (int, float))
                      and isinstance(b, (int, float)) else None),
            "judge_model": cur.get("judge_model"),
            "note": "informational - not part of the gate verdict",
        })
    return rows


def _regressed_questions(current: Dict[str, Any], baseline: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Golden questions whose recall or first_relevant_rank got worse."""
    base_rows = {r.get("id"): r for r in baseline.get("results", []) if r.get("id")}
    out = []
    for r in current.get("results", []):
        b = base_rows.get(r.get("id"))
        if not b:
            continue
        cur_recall, base_recall = r.get("recall_at_k"), b.get("recall_at_k")
        cur_rank, base_rank = r.get("first_relevant_rank"), b.get("first_relevant_rank")
        recall_dropped = (cur_recall is not None and base_recall is not None and cur_recall < base_recall)
        rank_worse = (cur_rank is not None and base_rank is not None and cur_rank > base_rank)
        if recall_dropped or rank_worse:
            out.append({
                "id": r.get("id"),
                "question": (r.get("question") or "")[:80],
                "recall": f"{base_recall} → {cur_recall}",
                "rank": f"{base_rank} → {cur_rank}" if rank_worse else None,
            })
    return out


def evaluate(snapshot_id: str, against: Optional[str] = None) -> Dict[str, Any]:
    """Diff snapshot `snapshot_id` against the baseline (or another snapshot)."""
    current = load_snapshot(snapshot_id)
    if not current:
        raise ValueError(f"Snapshot '{snapshot_id}' not found")
    if against:
        baseline = load_snapshot(against)
        if not baseline:
            raise ValueError(f"Comparison snapshot '{against}' not found")
    else:
        baseline = get_baseline()
        if not baseline:
            raise ValueError("No baseline set — run a suite and press 'Set as baseline' first")
    return diff_snapshots(current, baseline)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Diff an eval snapshot against the baseline")
    ap.add_argument("snapshot_id", help="snapshot to evaluate (see eval/snapshots/)")
    ap.add_argument("--against", help="diff against this snapshot id instead of BASELINE.json")
    args = ap.parse_args(argv)
    try:
        result = evaluate(args.snapshot_id, args.against)
    except ValueError as exc:
        print(f"gate error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "verdict": result["verdict"],
        "worst_metric": result["worst_metric"],
        "worst_drop": result["worst_drop"],
        "regressed_ids": result["regressed_ids"],
    }, ensure_ascii=False, indent=2))
    return 1 if result["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())