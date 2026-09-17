"""Phase 12 — full knowledge-base reset (real state, never fabricated).

    .venv\\Scripts\\python.exe scripts\\reset_database.py              # prompt to confirm
    .venv\\Scripts\\python.exe scripts\\reset_database.py --yes        # no prompt
    .venv\\Scripts\\python.exe scripts\\reset_database.py --purge-documents

Deletes Cognee graph + vectors + relational records (cognee.forget(everything=True)),
drops every remaining Qdrant collection, and clears data/metadata JSONs.
Source PDFs in data/documents are KEPT unless --purge-documents is passed.

Stop the Streamlit app (and any other python process holding the Ladybug
graph file) before running — the .lbug DB can't be deleted under a file lock
(Windows error 33).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config.settings import get_settings  # noqa: E402
from app.knowledge.cognee_manager import CognifyManager  # noqa: E402


def _confirm() -> bool:
    if "--yes" in sys.argv:
        return True
    answer = input("Delete ALL knowledge state (graph, vectors, metadata)? [y/N] ")
    return answer.strip().lower() == "y"


def main() -> int:
    settings = get_settings()
    if not _confirm():
        print("Aborted — nothing deleted.")
        return 1

    manager = CognifyManager(settings)
    result = manager.reset()
    print(f"cognee.forget(everything=True): {result.get('cognee')}")
    print(f"qdrant collections dropped    : {result.get('qdrant_dropped')}")

    for meta_file in ("ingested.json", "documents.json"):
        path = settings.metadata_dir / meta_file
        if path.exists():
            path.unlink()
            print(f"removed                       : {path.name}")

    if "--purge-documents" in sys.argv:
        removed = 0
        for path in settings.document_dir.iterdir():
            if path.is_file():
                path.unlink()
                removed += 1
        print(f"purged documents              : {removed} file(s) from {settings.document_dir}")
    else:
        kept = [p.name for p in settings.document_dir.iterdir() if p.is_file()]
        print(f"documents kept                : {len(kept)} in {settings.document_dir}")

    # REAL after-state — verify, don't assume.
    status = manager.get_status()
    graph = status.get("graph", {})
    print("\nafter-state:")
    if "error" in graph:
        # After a full forget, the dataset itself is gone — the graph error
        # "dataset not found (not ingested yet)" IS the expected empty state.
        print(f"  graph   : {graph['error']}")
    else:
        print(f"  graph   : {graph.get('nodes')} nodes / {graph.get('relationships')} relationships")
    collections = status.get("vector", {}).get("collections", {})
    print(f"  qdrant  : {len(collections)} collection(s)")
    for name, info in sorted(collections.items()):
        print(f"            {name:<32} {info['points_count']:>5} pts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())