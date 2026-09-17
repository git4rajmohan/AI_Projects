"""Append-only JSONL session / message store."""
from __future__ import annotations

import datetime
import json
import threading
from pathlib import Path
from typing import Any, Optional

from mcp_app.observability.logger import get_logger

log = get_logger(__name__)


class JSONLStore:
    """
    Thread-safe append-only JSONL file store.

    Each written record is a JSON object on its own line.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, record: dict[str, Any]) -> None:
        """Append a dict record as a JSONL line."""
        record.setdefault(
            "ts",
            datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
        )
        line = json.dumps(record, default=str, ensure_ascii=False)
        with self._lock:
            try:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError as exc:
                log.warning("JSONLStore.append failed: %s", exc)

    def read_all(self) -> list[dict[str, Any]]:
        """Read and parse all records from the file."""
        if not self._path.exists():
            return []
        records: list[dict[str, Any]] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    log.warning("JSONLStore line %d parse error: %s", lineno, exc)
        return records

    @property
    def path(self) -> Path:
        return self._path
