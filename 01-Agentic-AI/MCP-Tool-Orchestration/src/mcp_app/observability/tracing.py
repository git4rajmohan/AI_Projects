"""JSONL tracing – writes structured events to a rotating trace file."""
from __future__ import annotations

import datetime
import json
import threading
from pathlib import Path
from typing import Any, Optional

from mcp_app.observability.logger import get_logger, get_session_id

log = get_logger(__name__)

_lock = threading.Lock()
_trace_file: Optional[Path] = None
_redactor: Optional[Any] = None  # injected lazily to avoid circular import


def init_tracing(trace_dir: str, redactor: Any = None) -> None:
    """
    Initialise the trace directory and file.

    Args:
        trace_dir: Directory path where trace.jsonl will be written.
        redactor:  Optional callable(payload) -> redacted_payload.
                   Typically storage.redact.redact_dict.
    """
    global _trace_file, _redactor
    path = Path(trace_dir)
    path.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now(tz=datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
    _trace_file = path / f"trace_{ts}.jsonl"
    _redactor = redactor
    log.debug("Tracing initialised → %s", _trace_file)


def trace_event(
    event_type: str,
    payload: dict[str, Any],
    session_id: Optional[str] = None,
) -> None:
    """
    Append a JSONL trace record.

    The payload is redacted before writing.

    Args:
        event_type:  e.g. "llm_request", "tool_call", "tool_result"
        payload:     Arbitrary dict; sensitive keys will be redacted.
        session_id:  Override; defaults to context-var value.
    """
    if _trace_file is None:
        return

    sid = session_id or get_session_id() or "unknown"
    ts = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()

    record = {
        "ts": ts,
        "session_id": sid,
        "event_type": event_type,
        "payload": _redactor(payload) if _redactor else payload,
    }

    try:
        line = json.dumps(record, default=str, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        log.warning("trace_event serialisation failed: %s", exc)
        return

    with _lock:
        try:
            with _trace_file.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError as exc:
            log.warning("trace_event write failed: %s", exc)
