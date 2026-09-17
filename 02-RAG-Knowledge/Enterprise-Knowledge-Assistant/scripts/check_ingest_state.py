"""Check ingestion state after the failed Phase 6 run (REAL counts only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config.settings import get_settings  # noqa: E402
from app.knowledge.cognee_manager import CognifyManager  # noqa: E402


def main() -> int:
    m = CognifyManager(get_settings())
    s = m.get_status()
    g = s["graph"]
    if "error" in g:
        print("graph ERROR:", g["error"])
    else:
        print("graph nodes:", g.get("nodes"), "relationships:", g.get("relationships"))
        print("node_types:", json.dumps(g.get("node_types", {})))
    for name, info in sorted(s["vector"]["collections"].items()):
        print(f"{name:<32} {info['points_count']:>5} pts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())