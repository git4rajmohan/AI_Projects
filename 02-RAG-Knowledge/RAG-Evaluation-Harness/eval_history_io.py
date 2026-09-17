"""
eval_history_io.py
==================
Lightweight JSON-file persistence for evaluation runs.

Why not SQLite? See the architectural discussion in the chat history. The
in-app result set is small (tens to hundreds of floats per run), runs are
discrete experiments rather than a continuous stream, and we want zero
schema-migration overhead. One timestamped JSON file per run is enough
to support "save this run", "load a previous run", and "delete a run"
without a database.

File layout
-----------
    <project_root>/runs/
        2026-06-14T12-34-56_8f3a2b.json
        2026-06-14T13-05-11_2c91de.json
        ...

Filename format: ISO-like timestamp + 6-char content hash, safe across
Windows filesystems (no colons). The 6-char hash prefix makes duplicate
timestamps (same second) distinguishable and gives every file a unique id.

Why `runs/` and not `eval_history/`? The module name `eval_history_io`
sits next to a `runs/` folder on disk, which keeps the import surface
unambiguous. A directory named `eval_history/` next to `eval_history_io.py`
caused a name-shadowing collision: Python's import machinery would try
to load the directory as a package and fail. The directory is now
called `runs/` to avoid that.

JSON schema
-----------
Each file contains a single JSON object with this shape:

    {
        "version": 1,
        "saved_at": "2026-06-14T12:34:56",
        "title": "GLM-4.7 baseline",      # user-supplied one-liner
        "description": "Original prompt", # optional multi-line context
        "test_set_name": "ARIA_data.csv (2 rows)",  # auto-filled
        "rubric_preset": "Factual QA Rubric",      # auto-filled
        "label": "GLM-4.7 baseline",     # legacy alias for title
        "config": {                       # serialized AppConfig
            "llm_model": "zai-org/GLM-4.7",
            "llm_api_endpoint": "https://...",
            "llm_temperature": 0.0,
            "llm_max_tokens": 8192,
            "selected_metrics": [...],
            "rag_endpoint": "https://..."
        },
        "results": [                      # list of EvaluationResult dicts
            {
                "row_number": 1,
                "question": "...",
                "response": "...",
                "reference": "...",
                "retrieved_contexts": [...],
                "scores": {"Faithfulness": 0.9, ...},
                "reasons": {"Rubrics score": "..."}
            }
        ]
    }
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


# Where saved runs live. Resolved relative to the project root (the
# directory that contains this file's parent). If the env var is set,
# it wins — useful for CI runs that want eval_history somewhere else.
_HISTORY_DIR_ENV = "EVAL_HISTORY_DIR"

# Filename-safe timestamp: Windows file systems reject colons in paths,
# so we replace the time separators in the ISO string with dashes.
_TIMESTAMP_FMT = "%Y-%m-%dT%H-%M-%S"
_HASH_LEN = 6

# Anything that isn't a letter, digit, dash, underscore, or dot becomes
# an underscore. Keeps filenames portable.
_LABEL_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def history_dir() -> Path:
    """Return the absolute path to the runs/ directory, creating it on
    first use. Honors the EVAL_HISTORY_DIR env var for overrides.

    The directory is intentionally named `runs/` (not `eval_history/`)
    to avoid a name-shadowing collision with this module
    `eval_history_io.py` — having both an `eval_history/` directory
    and a same-prefix module on the import path confuses Python and
    Streamlit's script runner.
    """
    import os

    raw = os.getenv(_HISTORY_DIR_ENV)
    if raw:
        path = Path(raw).expanduser().resolve()
    else:
        # <project_root>/runs/, where project_root is the parent
        # of the directory containing this file.
        path = Path(__file__).resolve().parent / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_label(label: str) -> str:
    """Sanitize the user-supplied label so it can safely appear in a
    filename. Empty input becomes 'run'."""
    cleaned = _LABEL_SAFE.sub("_", label.strip()).strip("._-")
    return cleaned or "run"


def _content_hash(payload: dict[str, Any]) -> str:
    """Short, deterministic hash so two runs saved in the same second
    still get distinct filenames (and the same content gets the same
    filename, which is nice for de-duplication)."""
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:_HASH_LEN]


def build_run_filename(label: str, results: list[Any]) -> str:
    """Build the timestamped filename for a new run."""
    timestamp = datetime.now().strftime(_TIMESTAMP_FMT)
    # Hash a minimal fingerprint of the results so two saves of
    # identical content collapse to the same filename.
    fingerprint = {
        "rows": [
            {"q": getattr(r, "question", ""), "scores": getattr(r, "scores", {})}
            for r in results
        ]
    }
    return f"{timestamp}_{_content_hash(fingerprint)}.json"


def save_run(
    results: list[Any],
    config: Any,
    *,
    title: str = "",
    description: str = "",
    test_set_name: str = "",
    rubric_preset: str = "",
    label: str = "",  # backwards-compat alias for `title`
) -> Path:
    """Persist the current evaluation results to a timestamped JSON file.

    The four user-facing fields (title, description, test_set_name,
    rubric_preset) are all stored in the JSON so a later comparison can
    show "what changed" without the user having to remember.

    Returns the path to the new file. If a file with the same content
    hash already exists, that file is returned unchanged (no overwrite,
    no duplicate).
    """
    # `label` is kept as a positional/keyword alias for `title` so any
    # older caller (or smoke test) keeps working.
    if label and not title:
        title = label

    # Trim and validate the title. A title is the one thing a user
    # *must* provide — without it the saved file has no human-friendly
    # identity.
    safe_title = _safe_label(title) if title else ""
    safe_description = (description or "").strip()
    safe_test_set_name = (test_set_name or "").strip()
    safe_rubric_preset = (rubric_preset or "").strip()

    timestamp = datetime.now().strftime(_TIMESTAMP_FMT)
    fingerprint = {
        "rows": [
            {"q": getattr(r, "question", ""), "scores": getattr(r, "scores", {})}
            for r in results
        ]
    }
    content_hash = _content_hash(fingerprint)

    # Filename uses the title when available, otherwise just timestamp
    # + content hash. The hash is always present so de-duping works
    # even when the user re-saves with the same title.
    if safe_title:
        filename = f"{timestamp}_{safe_title}_{content_hash}.json"
    else:
        filename = f"{timestamp}_{content_hash}.json"

    target = history_dir() / filename
    if target.exists():
        # De-dupe: same content saved twice in the same second.
        return target

    payload = {
        "version": 1,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "title": title or f"Run of {len(results)} row(s)",
        "description": safe_description,
        "test_set_name": safe_test_set_name,
        "rubric_preset": safe_rubric_preset,
        # `label` is kept in the payload for backwards compatibility with
        # any readers that look for the old field name.
        "label": title or f"Run of {len(results)} row(s)",
        "filename": filename,
        "config": _serialize_config(config),
        "results": [_serialize_result(r) for r in results],
    }
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def runs_in_date_range(days: int | None) -> list[dict[str, Any]]:
    """Return saved runs whose timestamp is within the last `days` days
    (or all of them when `days` is None), sorted oldest -> newest so
    a line chart reads left-to-right as time progresses.

    Filenames start with an ISO-like timestamp string, so a string
    compare on the filename prefix is equivalent to comparing the
    actual timestamp. This avoids parsing the JSON or stat'ing mtimes.
    """
    all_runs = list_runs()  # newest first
    if days is None:
        all_runs.reverse()  # oldest first for chart-friendly order
        return all_runs

    cutoff = datetime.now() - timedelta(days=days)
    cutoff_prefix = cutoff.strftime(_TIMESTAMP_FMT)
    in_range = [entry for entry in all_runs if entry["filename"] >= f"{cutoff_prefix}"]
    in_range.reverse()  # oldest first
    return in_range


def list_runs() -> list[dict[str, Any]]:
    """Return saved runs sorted newest-first. Each entry has:
        - filename (str, bare name on disk)
        - path (Path, absolute)
        - saved_at (str, ISO)
        - label (str)
        - row_count (int)
        - size_kb (float)
    """
    out: list[dict[str, Any]] = []
    for path in history_dir().glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            # Skip corrupted files; show them in the UI as broken.
            out.append(
                {
                    "filename": path.name,
                    "path": path,
                    "saved_at": "",
                    "label": "(corrupted file)",
                    "row_count": 0,
                    "size_kb": path.stat().st_size / 1024.0,
                    "broken": True,
                }
            )
            continue
        out.append(
            {
                "filename": path.name,
                "path": path,
                "saved_at": data.get("saved_at", ""),
                "label": data.get("label", path.stem),
                "row_count": len(data.get("results", [])),
                "size_kb": path.stat().st_size / 1024.0,
                "broken": False,
            }
        )
    # Newest first (filename starts with ISO timestamp, so string sort works).
    out.sort(key=lambda entry: entry["filename"], reverse=True)
    return out


def load_run(filename: str) -> dict[str, Any]:
    """Read a saved run from disk and return its parsed payload.

    Raises FileNotFoundError if the file is gone, or json.JSONDecodeError
    if it's corrupted. Callers should handle both.
    """
    path = history_dir() / filename
    return json.loads(path.read_text(encoding="utf-8"))


def delete_run(filename: str) -> bool:
    """Delete a saved run. Returns True if a file was actually removed."""
    path = history_dir() / filename
    if not path.exists():
        return False
    path.unlink()
    return True


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------
def _serialize_config(config: Any) -> dict[str, Any]:
    """Turn an AppConfig (or any dataclass with the same fields) into a
    plain dict for JSON. We do not include the API key."""
    if config is None:
        return {}
    try:
        data = asdict(config)
    except TypeError:
        return {}
    # Never persist secrets.
    data.pop("llm_api_key", None)
    return data


def _serialize_result(result: Any) -> dict[str, Any]:
    """Turn an EvaluationResult (or dict) into a plain JSON-safe dict."""
    if isinstance(result, dict):
        return result
    return {
        "row_number": getattr(result, "row_number", 0),
        "question": getattr(result, "question", ""),
        "response": getattr(result, "response", ""),
        "reference": getattr(result, "reference", ""),
        "retrieved_contexts": list(getattr(result, "retrieved_contexts", [])),
        "scores": dict(getattr(result, "scores", {})),
        "reasons": dict(getattr(result, "reasons", {})),
    }
