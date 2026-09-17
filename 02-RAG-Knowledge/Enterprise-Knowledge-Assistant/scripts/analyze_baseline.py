"""Analyze baseline evaluation results — failure taxonomy + judge spot-check."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

data = json.loads(Path("evaluation/baseline/results.json").read_text(encoding="utf-8"))
res = data["results"]

reason_counts: Counter[str] = Counter()
for r in res:
    for reason in r["failure_reasons"]:
        reason_counts[reason.split("(")[0].strip()[:70]] += 1
print("--- failure reason taxonomy ---")
for key, count in reason_counts.most_common():
    print(f"{count:3d}  {key}")

print()
print("--- per-category pass rate ---")
cat_counts: Counter[str] = Counter()
cat_pass: Counter[str] = Counter()
for r in res:
    cat_counts[r["category"]] += 1
    if r["passed"]:
        cat_pass[r["category"]] += 1
for cat in sorted(cat_counts):
    print(f"{cat:12s} {cat_pass[cat]:2d}/{cat_counts[cat]:2d}")

print()
print("--- unfaithful rows: first unsupported claim (judge audit) ---")
for r in res:
    if r["faithful"] is False and r["unsupported_claims"]:
        first = r["unsupported_claims"][0].replace("\n", " ")[:110]
        print(f"[{r['id']}] {first}")