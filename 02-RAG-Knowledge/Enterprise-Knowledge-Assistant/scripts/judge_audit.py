"""Judge audit: check judge-flagged claims against the actual evidence context."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

data = json.loads(Path("evaluation/baseline/results.json").read_text(encoding="utf-8"))


def audit(row_id: str, probes: list[str]) -> None:
    row = next(r for r in data["results"] if r["id"] == row_id)
    context = row["context"].lower()
    print(f"[{row_id}] faithful={row['faithful']}")
    for probe in probes:
        present = probe.lower() in context
        print(f"   {'PRESENT' if present else 'MISSING':8s} {probe!r}")
    print()


audit("g-036", ["20 days per year", "maximum of 20 days", "6.15", "30 days", "11+ years", "year 11"])
audit("g-039", ["vpn", "any network outside", "working remotely on any network"])
audit("g-040", ["12 weeks", "100%", "within 12 months", "6 months"])
audit("g-058", ["80%", "dental premium", "vsp", "100%", "first 4%", "23,500", "$325"])
audit("g-038", ["notify hr", "primary remote work location", "remote work agreement"])