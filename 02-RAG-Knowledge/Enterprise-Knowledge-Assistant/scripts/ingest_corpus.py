"""Phase 6 verification run — ingest the full corpus via Cognee, print REAL counts.

Usage:
    .venv\\Scripts\\python.exe scripts\\ingest_corpus.py            # all supported files
    .venv\\Scripts\\python.exe scripts\\ingest_corpus.py file1.pdf   # explicit subset

Re-running with no changes skips everything (hash ledger) and reprints the
real final Qdrant vector counts — that IS the duplicate-skip verification.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config.settings import get_settings  # noqa: E402
from app.ingestion.document_manager import SUPPORTED_EXTENSIONS  # noqa: E402
from app.knowledge.cognee_manager import CognifyManager  # noqa: E402
from app.vectorstore import qdrant_manager  # noqa: E402


def _to_jsonable(obj: Any) -> Any:
    """json.dumps with UUID dict keys / values (cognify returns UUID-keyed dicts)."""
    match obj:
        case dict():
            return {str(k): _to_jsonable(v) for k, v in obj.items()}
        case list() | tuple() | set():
            return [_to_jsonable(v) for v in obj]
        case Path():
            return str(obj)
        case _:
            return obj


def main() -> int:
    settings = get_settings()
    if sys.argv[1:]:
        paths = [
            Path(p) if Path(p).is_absolute() else settings.document_dir / p for p in sys.argv[1:]
        ]
    else:
        paths = sorted(
            p
            for p in settings.document_dir.iterdir()
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
        )
    if not paths:
        print("No documents found in", settings.document_dir)
        return 1

    manager = CognifyManager(settings)
    print(f"Qdrant      : {settings.qdrant_url}")
    print(f"Discovered  : {len(paths)} document(s)")
    print(f"Ingesting   : {[p.name for p in paths]}\n")

    t0 = time.perf_counter()
    counts = manager.ingest_all(paths)
    elapsed = time.perf_counter() - t0

    # REAL processing counts — never fabricated.
    print(json.dumps(counts, indent=2))
    print(f"elapsed     : {elapsed:.1f}s\n")

    status = manager.get_status()
    graph = status.get("graph", {})
    if "error" in graph:
        print(f"graph       : ERROR {graph['error']}")
    else:
        print(
            f"graph       : {graph.get('nodes', '?')} nodes / "
            f"{graph.get('relationships', '?')} relationships"
        )
        for dtype, n in sorted(graph.get("node_types", {}).items()):
            print(f"              {dtype:<16} {n}")

    print("qdrant      :")
    for name, info in sorted(status.get("vector", {}).get("collections", {}).items()):
        print(
            f"              {name:<32} {info['points_count']:>5} pts  "
            f"size={info['vector_size']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())