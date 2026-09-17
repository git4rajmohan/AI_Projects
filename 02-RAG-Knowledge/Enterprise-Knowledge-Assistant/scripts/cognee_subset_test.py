"""Phase 5 verification run — ingest 1-2 PDFs via Cognee, print REAL counts only.

Usage:
    .venv\\Scripts\\python.exe scripts\\cognee_subset_test.py [file1.pdf file2.pdf]

Defaults to holiday-schedule.pdf + benefits-overview.pdf (plan.md Phase 5).
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
from app.knowledge.cognee_manager import CognifyManager  # noqa: E402

DEFAULT_SUBSET = ["holiday-schedule.pdf", "benefits-overview.pdf"]


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
    subset = sys.argv[1:] or DEFAULT_SUBSET
    paths = [Path(p) if Path(p).is_absolute() else PROJECT_ROOT / "data" / "documents" / p for p in subset]
    settings = get_settings()
    manager = CognifyManager(settings)

    print(f"LLM endpoint      : {manager.settings.cloud_base_url if manager.settings.is_cloud_provider else manager.settings.local_base_url} (model {settings.llm_model})")
    print(f"Embedding endpoint: local daemon, model {settings.embed_model}")
    print(f"Qdrant            : {settings.qdrant_url}")
    print(f"Ingesting         : {[p.name for p in paths]}\n")

    t0 = time.perf_counter()
    added = manager.add_documents(paths)
    print(f"add_documents     : {json.dumps(_to_jsonable(added), default=str, indent=2)}")

    processed = manager.process()
    print(f"cognify result    : {json.dumps(_to_jsonable(processed), default=str, indent=2)}")
    print(f"elapsed           : {time.perf_counter() - t0:.1f}s\n")

    status = manager.get_status()
    print(json.dumps(_to_jsonable(status), default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())