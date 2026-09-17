"""Structured logging setup with optional correlation-ID injection."""
from __future__ import annotations

import contextvars
import logging
import sys
from typing import Optional

# Context vars for correlation ids
_session_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "session_id", default=""
)
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)


def set_session_id(session_id: str) -> None:
    _session_id_var.set(session_id)


def set_request_id(request_id: str) -> None:
    _request_id_var.set(request_id)


def get_session_id() -> str:
    return _session_id_var.get()


def get_request_id() -> str:
    return _request_id_var.get()


class _CorrelationFilter(logging.Filter):
    """Inject session_id / request_id into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.session_id = _session_id_var.get() or "-"
        record.request_id = _request_id_var.get() or "-"
        return True


def setup_logging(level: str = "INFO", log_dir: Optional[str] = None) -> None:
    """
    Configure root logger.

    - Console handler always active.
    - File handler added when log_dir is provided.
    - Correlation IDs (session_id, request_id) included in format.
    """
    import os
    from pathlib import Path

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    fmt = (
        "%(asctime)s %(levelname)-8s "
        "[%(session_id)s|%(request_id)s] "
        "%(name)s: %(message)s"
    )
    formatter = logging.Formatter(fmt, datefmt="%Y-%m-%dT%H:%M:%S")
    correlation_filter = _CorrelationFilter()

    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Remove any existing handlers to avoid duplication on re-init
    root.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(correlation_filter)
    root.addHandler(console_handler)

    # Optional file handler
    if log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(
            log_path / "mcp_app.log", encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(correlation_filter)
        root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger (child of root, inherits setup)."""
    return logging.getLogger(name)
